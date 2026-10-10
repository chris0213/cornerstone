"""月报定时生成与邮件推送

配置存 settings（key=report_schedule）：
    {"enabled": bool, "day": 1-28, "hour": 0-23, "minute": 0-59, "email_to": "a@b.c"}

调度器每分钟检查一次：到达配置时间且启用时，生成上个月的月报并邮件推送。
幂等：该月已存在 done 记录则跳过，进程重启/重复触发不会重复生成与发送。
"""
import json
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.report import MonthlyReport
from src.models.setting import Setting
from src.services.report_generator import (
    collect_report_data,
    generate_report_pdf,
    get_report_filename,
    REPORT_DIR,
)

logger = logging.getLogger(__name__)

SCHEDULE_KEY = "report_schedule"
SCHEDULE_DEFAULTS = {
    "enabled": False,
    "day": 1,       # 每月几号执行（1-28，避免月份天数差异）
    "hour": 9,      # 北京时间
    "minute": 0,
    "email_to": "",  # 留空只生成不发送
}

BEIJING_TZ = timezone(timedelta(hours=8))


class ReportError(Exception):
    """月报生成失败（API 层转换为 HTTP 错误）"""


def _validate(config: dict) -> dict:
    """校验并规范化配置，非法时抛 ValueError"""
    day = int(config.get("day", 1))
    hour = int(config.get("hour", 9))
    minute = int(config.get("minute", 0))
    email_to = str(config.get("email_to", "") or "").strip()

    if not 1 <= day <= 28:
        raise ValueError("执行日期须在 1-28 之间")
    if not 0 <= hour <= 23:
        raise ValueError("小时须在 0-23 之间")
    if not 0 <= minute <= 59:
        raise ValueError("分钟须在 0-59 之间")
    if email_to and "@" not in email_to:
        raise ValueError("收件邮箱格式不正确")

    return {
        "enabled": bool(config.get("enabled", False)),
        "day": day,
        "hour": hour,
        "minute": minute,
        "email_to": email_to,
    }


async def get_schedule(db: AsyncSession) -> dict:
    """读取定时推送配置（无记录时返回默认值）"""
    result = await db.execute(select(Setting.value).where(Setting.key == SCHEDULE_KEY))
    raw = result.scalar_one_or_none()
    if not raw:
        return dict(SCHEDULE_DEFAULTS)
    try:
        saved = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        saved = {}
    return {**SCHEDULE_DEFAULTS, **saved}


async def save_schedule(db: AsyncSession, config: dict) -> dict:
    """校验并保存定时推送配置（每分钟由调度器读取，保存即生效）"""
    cleaned = _validate(config)
    stmt = select(Setting).where(Setting.key == SCHEDULE_KEY)
    setting = (await db.execute(stmt)).scalar_one_or_none()
    if setting:
        setting.value = json.dumps(cleaned, ensure_ascii=False)
    else:
        db.add(Setting(key=SCHEDULE_KEY, value=json.dumps(cleaned, ensure_ascii=False)))
    await db.commit()
    return cleaned


async def generate_report(db: AsyncSession, year: int, month: int, generated_by: str) -> dict:
    """生成指定月份月报 PDF 并落库（手动端点与定时任务共用）

    同月份只保留最新一次：生成前删除旧记录与旧文件。
    失败抛 ReportError。
    """
    data = await collect_report_data(year, month, db)

    report_dir = REPORT_DIR / str(year)
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = get_report_filename(data)
    output_path = str(report_dir / filename)

    # 删除该月份旧记录（只保留最新一次）
    old = (await db.execute(
        select(MonthlyReport).where(MonthlyReport.year == year, MonthlyReport.month == month)
    )).scalars().all()
    for record in old:
        if record.file_path and os.path.exists(record.file_path):
            try:
                os.remove(record.file_path)
            except OSError:
                pass
    await db.execute(
        delete(MonthlyReport).where(MonthlyReport.year == year, MonthlyReport.month == month)
    )
    await db.commit()

    try:
        generate_report_pdf(data, output_path)
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise ReportError(f"月报生成失败: {e}") from e

    file_size = os.path.getsize(output_path)
    db.add(MonthlyReport(
        year=year, month=month,
        file_path=output_path, file_size=file_size,
        status="done", generated_by=generated_by,
        generated_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    return {"filename": filename, "file_path": output_path, "file_size": file_size}


async def _has_report(db: AsyncSession, year: int, month: int) -> bool:
    result = await db.execute(
        select(MonthlyReport.id).where(
            MonthlyReport.year == year,
            MonthlyReport.month == month,
            MonthlyReport.status == "done",
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def _send_report_email(smtp_cfg: dict, to_email: str, subject: str, pdf_path: str) -> None:
    """发送带 PDF 附件的月报邮件（同步 SMTP，配置不全时抛 RuntimeError）"""
    needed = ["smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from_email"]
    if not all(smtp_cfg.get(k) for k in needed):
        raise RuntimeError("SMTP 配置不完整")

    msg = MIMEMultipart()
    msg["From"] = formataddr(("Cornerstone 月报推送", smtp_cfg["smtp_from_email"]))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(
        f"您好：\n\n附件为 {subject}，请查收。\n\n——基石 Cornerstone 智能运维平台",
        "plain", "utf-8",
    ))
    with open(pdf_path, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=Path(pdf_path).name)
        msg.attach(part)

    with smtplib.SMTP(smtp_cfg["smtp_host"], smtp_cfg["smtp_port"], timeout=15) as server:
        server.starttls()
        server.login(smtp_cfg["smtp_username"], smtp_cfg["smtp_password"])
        server.sendmail(smtp_cfg["smtp_from_email"], [to_email], msg.as_string())


async def run_scheduled_report(db: AsyncSession) -> dict:
    """调度入口（每分钟调用）：到达配置时间则生成上月月报并推送

    返回执行结果 dict，便于日志与测试断言。
    """
    config = await get_schedule(db)
    if not config["enabled"]:
        return {"action": "disabled"}

    now = datetime.now(BEIJING_TZ)
    if (now.day, now.hour, now.minute) != (config["day"], config["hour"], config["minute"]):
        return {"action": "not_due"}

    # 报告月份 = 上个月
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)

    if await _has_report(db, year, month):
        return {"action": "skipped", "reason": "already_exists", "year": year, "month": month}

    try:
        result = await generate_report(db, year, month, generated_by="system_schedule")
    except ReportError as e:
        logger.error("定时月报生成失败 %04d-%02d: %s", year, month, e)
        return {"action": "failed", "error": str(e)}

    outcome = {"action": "generated", "year": year, "month": month,
               "filename": result["filename"], "email_sent": False}

    if config["email_to"]:
        from src.services.alert_service import AlertService  # 局部导入避免循环依赖
        try:
            smtp_cfg = await AlertService._get_notification_config(db)
            _send_report_email(
                smtp_cfg,
                config["email_to"],
                f"{year}年{month}月运营月报",
                result["file_path"],
            )
            outcome["email_sent"] = True
        except Exception as e:
            logger.warning("定时月报邮件发送失败（报告已生成）: %s", e)
            outcome["email_error"] = str(e)

    logger.info("定时月报已生成: %s email_sent=%s", result["filename"], outcome["email_sent"])
    return outcome
