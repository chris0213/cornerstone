"""月报定时生成与多渠道推送

配置存 settings（key=report_schedule）：
    {"enabled": bool, "day": 1-28, "hour": 0-23, "minute": 0-59, "email_to": "a@b.c",
     "channels": ["email","dingtalk","wechat","feishu"],
     "include_link": bool, "include_summary": bool, "link_base_url": "https://ops.example.com"}

调度器每分钟检查一次：到达配置时间且启用时，生成上个月的月报并按渠道推送。
- 邮件：带 PDF 附件（email_to 为空则跳过）
- 钉钉/企业微信/飞书：文本消息，内容含关键指标摘要与报告页下载链接（按 include_* 开关），
  webhook 地址复用「通知设置」中的配置。
幂等：该月已存在 done 记录则跳过，进程重启/重复触发不会重复生成与发送。
"""
import hashlib
import hmac
import json
import logging
import os
import smtplib
import time
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
    "channels": ["email"],          # 推送渠道：email/dingtalk/wechat/feishu
    "include_link": True,           # 聊天软件消息是否附报告页下载链接
    "include_summary": True,        # 聊天软件消息是否附关键指标摘要
    "link_base_url": "",            # 系统访问地址，生成下载链接用（如 https://ops.example.com）
}

VALID_CHANNELS = ("email", "dingtalk", "wechat", "feishu")
CHAT_CHANNELS = ("dingtalk", "wechat", "feishu")

SHARE_LINK_TTL = 7 * 24 * 3600  # 分享直链有效期 7 天

BEIJING_TZ = timezone(timedelta(hours=8))


def make_shared_link(base_url: str, year: int, month: int, now_ts: int | None = None) -> str:
    """生成免登录的月报分享直链（HMAC 签名 + 7 天有效期，点开直接下载 PDF）

    base_url 为系统访问地址；API 固定挂在域名根路径（前端 axios baseURL='/api/v1'
    为绝对路径），故只取 origin，自动忽略反代路径前缀（如 http://ip:8089/r）。
    """
    from urllib.parse import urlparse
    base = (base_url or "").strip().rstrip("/")
    if "://" not in base:
        base = f"http://{base}"
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    exp = int(now_ts if now_ts is not None else time.time()) + SHARE_LINK_TTL
    sig = sign_report(year, month, exp)
    return f"{origin}/api/v1/reports/monthly/shared-download/{year}/{month}?exp={exp}&sig={sig}"


def sign_report(year: int, month: int, exp: int) -> str:
    """HMAC-SHA256 签名（生成与验证共用）"""
    from src.config import settings
    msg = f"report:{year}:{month}:{exp}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def verify_shared_link(year: int, month: int, exp: int | None, sig: str | None) -> bool:
    """校验分享直链：签名匹配且未过期"""
    if not exp or not sig:
        return False
    if int(exp) < time.time():
        return False
    return hmac.compare_digest(sign_report(year, month, int(exp)), sig)


class ReportError(Exception):
    """月报生成失败（API 层转换为 HTTP 错误）"""


def _validate(config: dict) -> dict:
    """校验并规范化配置，非法时抛 ValueError"""
    day = int(config.get("day", 1))
    hour = int(config.get("hour", 9))
    minute = int(config.get("minute", 0))
    email_to = str(config.get("email_to", "") or "").strip()

    channels = config.get("channels")
    if channels is None:
        channels = list(SCHEDULE_DEFAULTS["channels"])  # 旧配置无此字段时兼容默认
    if not isinstance(channels, list):
        raise ValueError("推送渠道格式不正确")
    channels = [str(c).strip() for c in channels if str(c).strip()]
    unknown = [c for c in channels if c not in VALID_CHANNELS]
    if unknown:
        raise ValueError(f"不支持的推送渠道: {', '.join(unknown)}")

    include_link = bool(config.get("include_link", True))
    include_summary = bool(config.get("include_summary", True))
    link_base_url = str(config.get("link_base_url", "") or "").strip().rstrip("/")

    if not 1 <= day <= 28:
        raise ValueError("执行日期须在 1-28 之间")
    if not 0 <= hour <= 23:
        raise ValueError("小时须在 0-23 之间")
    if not 0 <= minute <= 59:
        raise ValueError("分钟须在 0-59 之间")
    if email_to and "@" not in email_to:
        raise ValueError("收件邮箱格式不正确")

    # 勾选聊天软件渠道时，至少选择一种消息内容
    if any(c in CHAT_CHANNELS for c in channels) and not (include_link or include_summary):
        raise ValueError("聊天软件推送至少需要选择一种消息内容（下载链接或关键指标）")

    return {
        "enabled": bool(config.get("enabled", False)),
        "day": day,
        "hour": hour,
        "minute": minute,
        "email_to": email_to,
        "channels": channels,
        "include_link": include_link,
        "include_summary": include_summary,
        "link_base_url": link_base_url,
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

    return {
        "filename": filename, "file_path": output_path, "file_size": file_size,
        "summary": {
            "cost_total": data.circuit_cost_total,
            "incident_count": data.incident_count,
            "availability_pct": data.availability_pct,
            "expiring_count": len(data.urgent_items) + len(data.warning_items),
        },
    }


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


def _build_chat_message(config: dict, year: int, month: int, summary: dict) -> str:
    """构建聊天软件推送文本（关键指标摘要 + 报告页下载链接，按开关拼装）"""
    lines = [f"【基石月报】{year}年{month}月运营月报已生成"]

    if config.get("include_summary", True):
        lines.append("")
        lines.append("关键指标：")
        lines.append(f"· 专线月租总费用：¥{summary.get('cost_total', 0):,}")
        lines.append(f"· 本月故障：{summary.get('incident_count', 0)} 起")
        avail = summary.get("availability_pct")
        if avail is not None:
            lines.append(f"· 网络可用性：{avail:.1f}%")
        lines.append(f"· 到期事项：{summary.get('expiring_count', 0)} 项")

    if config.get("include_link", True):
        base_url = (config.get("link_base_url") or "").strip()
        if base_url:
            lines.append("")
            lines.append(f"报告下载：{make_shared_link(base_url, year, month)}")

    return "\n".join(lines)


async def _send_chat_notifications(db: AsyncSession, config: dict, message: str) -> dict:
    """按已选聊天渠道发送消息，webhook 复用通知设置；逐渠道容错"""
    from src.services.alert_service import AlertService  # 局部导入避免循环依赖

    channels = [c for c in config.get("channels", []) if c in CHAT_CHANNELS]
    result: dict = {"sent": [], "failed": {}}
    if not channels:
        return result

    notify_cfg = await AlertService._get_notification_config(db)
    senders = {
        "dingtalk": AlertService._send_dingtalk_notification,
        "wechat": AlertService._send_wechat_notification,
        "feishu": AlertService._send_feishu_notification,
    }
    url_keys = {
        "dingtalk": "dingtalk_webhook_url",
        "wechat": "wechat_webhook_url",
        "feishu": "feishu_webhook_url",
    }

    for ch in channels:
        webhook = notify_cfg.get(url_keys[ch])
        if not webhook:
            logger.warning("月报推送跳过 %s：通知设置中未配置 webhook", ch)
            result["failed"][ch] = "webhook 未配置"
            continue
        try:
            await senders[ch](webhook, message)
            result["sent"].append(ch)
        except Exception as e:
            logger.warning("月报推送 %s 发送失败: %s", ch, e)
            result["failed"][ch] = str(e)
    return result


async def run_scheduled_report(db: AsyncSession) -> dict:
    """调度入口（每分钟调用）：到达配置时间则生成上月月报并按渠道推送

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

    channels = config.get("channels") or []
    outcome = {"action": "generated", "year": year, "month": month,
               "filename": result["filename"], "email_sent": False, "chat_sent": []}

    # 邮件渠道（带 PDF 附件）
    if "email" in channels and config["email_to"]:
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

    # 聊天软件渠道（摘要 + 下载链接文本消息）
    chat_result = await _send_chat_notifications(
        db, config, _build_chat_message(config, year, month, result.get("summary", {}))
    )
    outcome["chat_sent"] = chat_result["sent"]
    if chat_result["failed"]:
        outcome["chat_failed"] = chat_result["failed"]

    logger.info("定时月报已生成: %s email_sent=%s chat_sent=%s",
                result["filename"], outcome["email_sent"], outcome["chat_sent"])
    return outcome
