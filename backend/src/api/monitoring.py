from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.api.dependencies import get_current_active_user
from src.models.device import Device
from src.models.link_monitor import LinkMonitor
from src.models.ip_address import IPAddress
from src.services.monitor_service import run_monitoring_task, ping_host, determine_status, latest_snapshot_subquery
from src.services.scheduler_service import (
    get_current_interval,
    update_scheduler_interval,
    is_scheduler_running,
    start_scheduler,
    stop_scheduler
)

router = APIRouter(tags=["monitoring"])


@router.post("/run")
async def run_monitor(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """手动触发一次监控任务"""
    await run_monitoring_task(db)
    return {"message": "监控任务已执行"}


@router.get("/devices")
async def get_device_monitor_status(
    device_id: Optional[int] = Query(None, description="设备ID"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """获取设备监控状态（每设备最新一条快照）"""
    # 子查询回连：只取每设备最新一行，避免全表拉到内存去重
    snapshot_subquery, snapshot_onclause = latest_snapshot_subquery()
    query = (
        select(
            Device.id,
            Device.name,
            LinkMonitor.target_ip,
            LinkMonitor.latency,
            LinkMonitor.packet_loss,
            LinkMonitor.status,
            LinkMonitor.created_at
        )
        .join(LinkMonitor, Device.id == LinkMonitor.device_id)
        .join(snapshot_subquery, snapshot_onclause)
        .order_by(Device.id)
    )

    if device_id:
        query = query.where(Device.id == device_id)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "device_id": row[0],
            "device_name": row[1],
            "target_ip": row[2],
            "latency": row[3],
            "packet_loss": row[4],
            "status": row[5],
            "updated_at": row[6]
        }
        for row in rows
    ]


@router.get("/history/{device_id}")
async def get_device_monitor_history(
    device_id: int,
    limit: int = Query(100, description="返回记录数"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """获取设备监控历史数据"""
    query = (
        select(LinkMonitor)
        .where(LinkMonitor.device_id == device_id)
        .order_by(LinkMonitor.created_at.desc())
        .limit(limit)
    )
    
    result = await db.execute(query)
    records = result.scalars().all()
    
    return [
        {
            "latency": record.latency,
            "packet_loss": record.packet_loss,
            "status": record.status,
            "created_at": record.created_at.isoformat() if record.created_at else None
        }
        for record in records
    ]


@router.get("/summary")
async def get_monitor_summary(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """获取监控概览统计"""
    # 获取最新监控记录（每设备最新一条快照的三档状态计数）
    snapshot_subquery, snapshot_onclause = latest_snapshot_subquery()

    query = (
        select(
            LinkMonitor.status,
            func.count(LinkMonitor.device_id).label("count")
        )
        .join(snapshot_subquery, snapshot_onclause)
        .group_by(LinkMonitor.status)
    )
    
    result = await db.execute(query)
    status_counts = result.all()
    
    summary = {"normal": 0, "warning": 0, "critical": 0}
    for status, count in status_counts:
        if status in summary:
            summary[status] = count
    
    return summary


@router.post("/ping/{target_ip}")
async def ping_target(
    target_ip: str,
    current_user=Depends(get_current_active_user),
):
    """测试指定IP的连通性"""
    latency, packet_loss = await ping_host(target_ip)
    status = determine_status(latency, packet_loss)
    
    return {
        "target_ip": target_ip,
        "latency": latency,
        "packet_loss": packet_loss,
        "status": status
    }


@router.get("/scheduler/status")
async def get_scheduler_status(current_user=Depends(get_current_active_user)):
    """获取定时任务调度器状态"""
    return {
        "running": is_scheduler_running(),
        "interval_minutes": get_current_interval()
    }


@router.post("/scheduler/interval")
async def set_scheduler_interval(
    interval_minutes: int = Query(..., ge=1, le=60, description="定时任务间隔（分钟）"),
    current_user=Depends(get_current_active_user),
):
    """设置定时任务间隔"""
    if interval_minutes not in [1, 5, 10]:
        raise HTTPException(status_code=400, detail="间隔必须为1、5或10分钟")
    
    update_scheduler_interval(interval_minutes)
    return {"message": f"定时任务间隔已设置为{interval_minutes}分钟"}


@router.post("/scheduler/start")
async def start_monitor_scheduler(
    interval_minutes: int = Query(5, ge=1, le=60),
    current_user=Depends(get_current_active_user),
):
    """启动定时任务调度器"""
    if interval_minutes not in [1, 5, 10]:
        raise HTTPException(status_code=400, detail="间隔必须为1、5或10分钟")
    
    start_scheduler(interval_minutes)
    return {"message": f"定时任务调度器已启动，间隔{interval_minutes}分钟"}


@router.post("/scheduler/stop")
async def stop_monitor_scheduler(current_user=Depends(get_current_active_user)):
    """停止定时任务调度器"""
    stop_scheduler()
    return {"message": "定时任务调度器已停止"}
