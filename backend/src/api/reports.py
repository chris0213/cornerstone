"""运营月报 API"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.database import get_db
from src.models.report import MonthlyReport
from src.models.user import User
from src.api.auth import get_current_active_user
from src.api.dependencies import require_super_admin
from src.services.report_schedule_service import (
    ReportError,
    generate_report,
    get_schedule,
    save_schedule,
)

router = APIRouter(tags=["reports"])

BEIJING_TZ = timezone(timedelta(hours=8))


class ScheduleConfig(BaseModel):
    """定时推送配置"""
    enabled: bool
    day: int        # 每月 1-28 号
    hour: int       # 0-23
    minute: int     # 0-59
    email_to: str = ""  # 留空只生成不发送


def _require_manager_or_admin(current_user: User):
    """验证用户角色为 viewer 或 super_admin"""
    if current_user.role.name not in ['viewer', 'super_admin']:
        raise HTTPException(status_code=403, detail="需要IT负责人或管理员权限")


@router.get("/monthly/list")
async def list_monthly_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取已生成的月报列表"""
    _require_manager_or_admin(current_user)

    result = await db.execute(
        select(MonthlyReport)
        .order_by(desc(MonthlyReport.year), desc(MonthlyReport.month))
        .limit(12)
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
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """生成指定月份的月报 PDF"""
    _require_manager_or_admin(current_user)

    # 用北京时间确定年月
    bj_now = datetime.now(BEIJING_TZ)
    if not year:
        year = bj_now.year
    if not month:
        month = bj_now.month

    try:
        result = await generate_report(db, year, month, current_user.username)
    except ReportError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "message": "月报生成成功",
        "filename": result["filename"],
        "file_size": result["file_size"],
    }


@router.get("/schedule")
async def get_report_schedule(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取月报定时推送配置"""
    _require_manager_or_admin(current_user)
    return await get_schedule(db)


@router.put("/schedule")
async def update_report_schedule(
    config: ScheduleConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """更新月报定时推送配置（保存后下一分钟内生效）"""
    _require_manager_or_admin(current_user)
    try:
        return await save_schedule(db, config.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/monthly/download/{year}/{month}")
async def download_monthly_report(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """下载指定月份的月报 PDF"""
    _require_manager_or_admin(current_user)

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


@router.delete("/monthly/{year}/{month}")
async def delete_monthly_report(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """删除指定月份月报"""

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

    return {"message": "月报已删除"}