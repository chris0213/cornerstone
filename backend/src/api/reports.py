import logging
"""运营月报 API"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.database import get_db
from src.models.report import MonthlyReport
from src.models.user import User
from src.utils.ip_whitelist import get_client_ip_from_request
from src.utils.logger import audit_log
from src.services.report_schedule_service import (
    ReportError,
    generate_report,
    get_schedule,
    save_schedule,
    verify_shared_link,
)
from .dependencies import require_permission, require_super_admin

router = APIRouter(tags=["reports"])

BEIJING_TZ = timezone(timedelta(hours=8))


class ScheduleConfig(BaseModel):
    """定时推送配置"""
    enabled: bool
    day: int        # 每月 1-28 号
    hour: int       # 0-23
    minute: int     # 0-59
    email_to: str = ""  # 留空只生成不发送
    channels: list[str] = ["email"]          # email/dingtalk/wechat/feishu
    include_link: bool = True                # 聊天消息附下载链接
    include_summary: bool = True             # 聊天消息附关键指标
    link_base_url: str = ""                  # 系统访问地址（生成下载链接）


def _validate_year_month(year: int, month: int):
    """年月范围校验"""
    if not (2000 <= year <= 2100):
        raise HTTPException(status_code=400, detail="年份超出允许范围（2000-2100）")
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="月份须为 1-12")


@router.get("/monthly/list")
async def list_monthly_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:read"))
):
    """获取已生成的月报列表"""
    result = await db.execute(
        select(MonthlyReport)
        .order_by(desc(MonthlyReport.year), desc(MonthlyReport.month))
        .limit(36)
    )
    reports = result.scalars().all()

    return [
        {
            "id": r.id,
            "year": r.year,
            "month": r.month,
            "file_size": r.file_size,
            "status": r.status,
            "generated_by": r.generated_by,
            "generated_at": (r.generated_at + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if r.generated_at else "",
            "filename": Path(r.file_path).name if r.file_path else "",
        }
        for r in reports
    ]


@router.post("/monthly/generate")
async def generate_monthly_report(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:read"))
):
    """生成指定月份的月报 PDF"""
    # 用北京时间确定年月
    bj_now = datetime.now(BEIJING_TZ)
    if not year:
        year = bj_now.year
    if not month:
        month = bj_now.month
    _validate_year_month(year, month)

    try:
        result = await generate_report(db, year, month, current_user.username)
    except ReportError as e:
        logger.error(f"月报生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="月报生成失败，请稍后重试")

    await audit_log(
        db, current_user.id, "report", 0, "generate",
        {"year": year, "month": month, "filename": result["filename"]},
        get_client_ip_from_request(request)
    )

    return {
        "message": "月报生成成功",
        "filename": result["filename"],
        "file_size": result["file_size"],
    }


@router.get("/schedule")
async def get_report_schedule(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:read"))
):
    """获取月报定时推送配置"""
    return await get_schedule(db)


@router.put("/schedule")
async def update_report_schedule(
    config: ScheduleConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:read"))
):
    """更新月报定时推送配置（保存后下一分钟内生效）"""
    try:
        result = await save_schedule(db, config.model_dump())
    except ValueError as e:
        logger.warning(f"月报定时配置校验失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    await audit_log(
        db, current_user.id, "report", 0, "schedule_update",
        {"enabled": config.enabled, "day": config.day, "hour": config.hour,
         "minute": config.minute, "channels": config.channels},
        get_client_ip_from_request(request)
    )
    return result


@router.get("/monthly/download/{year}/{month}")
async def download_monthly_report(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:read"))
):
    """下载指定月份的月报 PDF"""
    _validate_year_month(year, month)

    result = await db.execute(
        select(MonthlyReport).where(
            MonthlyReport.year == year,
            MonthlyReport.month == month,
            MonthlyReport.status == "done"
        )
    )
    report = result.scalars().first()

    if not report:
        raise HTTPException(status_code=404, detail="该月份月报未生成，请先生成")

    if not os.path.exists(report.file_path):
        raise HTTPException(status_code=404, detail="月报文件不存在")

    filename = Path(report.file_path).name
    return FileResponse(
        report.file_path,
        media_type="application/pdf",
        filename=filename
    )


@router.get("/monthly/shared-download/{year}/{month}")
async def shared_download_monthly_report(
    year: int,
    month: int,
    exp: int,
    sig: str,
    db: AsyncSession = Depends(get_db),
):
    """分享直链下载月报 PDF（免登录，HMAC 签名校验，7 天有效期）

    链接由定时推送在聊天软件消息中生成，点开直接下载文件。
    """
    if not verify_shared_link(year, month, exp, sig):
        raise HTTPException(status_code=403, detail="链接无效或已过期")

    result = await db.execute(
        select(MonthlyReport).where(
            MonthlyReport.year == year,
            MonthlyReport.month == month,
            MonthlyReport.status == "done"
        )
    )
    report = result.scalars().first()

    if not report or not os.path.exists(report.file_path):
        raise HTTPException(status_code=404, detail="月报文件不存在")

    return FileResponse(
        report.file_path,
        media_type="application/pdf",
        filename=Path(report.file_path).name
    )


@router.delete("/monthly/{year}/{month}")
async def delete_monthly_report(
    year: int,
    month: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """删除指定月份月报"""
    _validate_year_month(year, month)

    result = await db.execute(
        select(MonthlyReport).where(
            MonthlyReport.year == year,
            MonthlyReport.month == month
        )
    )
    report = result.scalars().first()

    if not report:
        raise HTTPException(status_code=404, detail="月报记录不存在")

    # 删除文件
    if os.path.exists(report.file_path):
        os.remove(report.file_path)

    await db.delete(report)
    await db.commit()

    await audit_log(
        db, current_user.id, "report", 0, "delete",
        {"year": year, "month": month},
        get_client_ip_from_request(request)
    )

    return {"message": "月报已删除"}