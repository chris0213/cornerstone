from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, union_all, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import literal_column

from ..database import get_db
from ..api.dependencies import get_current_active_user
from ..models import InspectionDeviceResult, Backup, AuditLog, Device, Circuit
from ..models.user import User

router = APIRouter(tags=["timeline"])


@router.get("/events")
async def get_timeline_events(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    event_types: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    now = datetime.now(timezone.utc)
    if start_time is None:
        start_time = now - timedelta(hours=24)
    if end_time is None:
        end_time = now
    
    type_filter = None
    if event_types:
        type_filter = event_types.split(',')
    
    events = []
    
    # 1. 设备离线/恢复事件 - 从巡检结果中提取最近一次状态变化
    insp_query = (
        select(
            InspectionDeviceResult.id.label("event_id"),
            literal_column("'device_offline'").label("event_type"),
            literal_column("'error'").label("severity"),
            InspectionDeviceResult.sys_name.label("title"),
            InspectionDeviceResult.error_message.label("description"),
            literal_column("'device'").label("resource_type"),
            InspectionDeviceResult.device_id.label("resource_id"),
            Device.name.label("resource_name"),
            InspectionDeviceResult.scanned_at.label("occurred_at"),
            literal_column("'/devices/' || CAST(inspection_device_results.device_id AS TEXT)").label("detail_url")
        )
        .join(Device, InspectionDeviceResult.device_id == Device.id)
        .where(
            and_(
                InspectionDeviceResult.is_online == False,
                InspectionDeviceResult.scanned_at >= start_time,
                InspectionDeviceResult.scanned_at <= end_time
            )
        )
    )
    
    insp_result = await db.execute(insp_query)
    for row in insp_result.all():
        resource_name = row.sys_name if row.sys_name else row.resource_name
        if not type_filter or "device_offline" in type_filter:
            events.append({
                "id": f"insp_{row.event_id}",
                "event_type": row.event_type,
                "severity": row.severity,
                "title": f"{resource_name} 设备离线",
                "description": row.description or "设备无响应",
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "resource_name": resource_name,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                "detail_url": row.detail_url if row.resource_id else None,
                "source": "巡检"
            })
    
    insp_online_query = (
        select(
            InspectionDeviceResult.id.label("event_id"),
            literal_column("'device_online'").label("event_type"),
            literal_column("'info'").label("severity"),
            InspectionDeviceResult.sys_name.label("title"),
            literal_column("'设备恢复在线'").label("description"),
            literal_column("'device'").label("resource_type"),
            InspectionDeviceResult.device_id.label("resource_id"),
            Device.name.label("resource_name"),
            InspectionDeviceResult.scanned_at.label("occurred_at"),
            literal_column("'/devices/' || CAST(inspection_device_results.device_id AS TEXT)").label("detail_url")
        )
        .join(Device, InspectionDeviceResult.device_id == Device.id)
        .where(
            and_(
                InspectionDeviceResult.is_online == True,
                InspectionDeviceResult.scanned_at >= start_time,
                InspectionDeviceResult.scanned_at <= end_time
            )
        )
    )
    
    insp_online_result = await db.execute(insp_online_query)
    for row in insp_online_result.all():
        resource_name = row.sys_name if row.sys_name else row.resource_name
        if not type_filter or "device_online" in type_filter:
            events.append({
                "id": f"insp_online_{row.event_id}",
                "event_type": row.event_type,
                "severity": row.severity,
                "title": f"{resource_name} 设备恢复在线",
                "description": row.description,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "resource_name": resource_name,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                "detail_url": row.detail_url if row.resource_id else None,
                "source": "巡检"
            })
    
    # 2. 备份成功/失败/配置变更事件
    backup_query = select(Backup).where(
        and_(
            Backup.created_at >= start_time,
            Backup.created_at <= end_time
        )
    )
    
    backup_result = await db.execute(backup_query)
    for backup in backup_result.scalars().all():
        device_result = await db.execute(select(Device).where(Device.id == backup.device_id))
        device = device_result.scalar_one_or_none()
        device_name = device.name if device else f"Device {backup.device_id}"
        
        if backup.status == "failed":
            if not type_filter or "backup_fail" in type_filter:
                events.append({
                    "id": f"backup_{backup.id}",
                    "event_type": "backup_fail",
                    "severity": "error",
                    "title": f"{device_name} 备份失败",
                    "description": backup.error_message or "备份过程发生错误",
                    "resource_type": "device",
                    "resource_id": backup.device_id,
                    "resource_name": device_name,
                    "occurred_at": backup.created_at.isoformat() if backup.created_at else None,
                    "detail_url": f"/devices/{backup.device_id}" if backup.device_id else None,
                    "source": "备份"
                })
        elif backup.status == "success":
            if backup.has_change:
                if not type_filter or "config_change" in type_filter:
                    events.append({
                        "id": f"backup_change_{backup.id}",
                        "event_type": "config_change",
                        "severity": "warning",
                        "title": f"{device_name} 配置发生变更",
                        "description": backup.change_summary or "检测到配置变化",
                        "resource_type": "device",
                        "resource_id": backup.device_id,
                        "resource_name": device_name,
                        "occurred_at": backup.created_at.isoformat() if backup.created_at else None,
                        "detail_url": f"/devices/{backup.device_id}" if backup.device_id else None,
                        "source": "备份"
                    })
            elif not type_filter or "backup_success" in type_filter:
                events.append({
                    "id": f"backup_{backup.id}",
                    "event_type": "backup_success",
                    "severity": "info",
                    "title": f"{device_name} 备份成功",
                    "description": "配置备份完成，无变更",
                    "resource_type": "device",
                    "resource_id": backup.device_id,
                    "resource_name": device_name,
                    "occurred_at": backup.created_at.isoformat() if backup.created_at else None,
                    "detail_url": f"/devices/{backup.device_id}" if backup.device_id else None,
                    "source": "备份"
                })
    
    # 3. 系统审计日志事件（高危操作）
    audit_query = select(AuditLog).where(
        and_(
            AuditLog.created_at >= start_time,
            AuditLog.created_at <= end_time,
            AuditLog.action.in_(["删除", "删除专线", "删除设备", "删除IP", "回滚", "重置密码"])
        )
    )
    
    audit_result = await db.execute(audit_query)
    for log in audit_result.scalars().all():
        if not type_filter or "system" in type_filter:
            events.append({
                "id": f"audit_{log.id}",
                "event_type": "system",
                "severity": "warning",
                "title": log.action,
                "description": log.detail or "",
                "resource_type": log.resource,
                "resource_id": None,
                "resource_name": log.resource or "系统",
                "occurred_at": log.created_at.isoformat() if log.created_at else None,
                "detail_url": None,
                "source": "系统"
            })
    
    # 按时间倒序排序
    events.sort(key=lambda x: x["occurred_at"] or "", reverse=True)
    
    total = len(events)
    has_more = total > limit
    events = events[:limit]
    
    return {
        "events": events,
        "total": total,
        "has_more": has_more
    }