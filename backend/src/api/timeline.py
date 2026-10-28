from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.dependencies import get_current_active_user
from .dashboard.common import to_naive_bjt
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
    # 时间口径统一为 naive 北京挂钟：
    # - 前端传本地挂钟字符串（无时区后缀）→ naive 原样；
    # - 兼容旧调用方传 UTC aware ISO → to_naive_bjt 归一为北京挂钟；
    # - 最终格式化为 'YYYY-MM-DD HH:MM:SS' 字符串绑定：
    #   SQLite 列存该格式，datetime 对象绑定可能携带 T 分隔/时区后缀导致
    #   字符串比较错位（T > 空格使 end 条件恒假）；PG 下 timestamptz 按字符串解析，
    #   依赖 session timezone（生产 compose TZ=Asia/Shanghai）。
    # ⚠ PG 行为需在 PG 环境验证后才能认为完全闭合。
    def _norm_bound_time(dt: datetime) -> str:
        return to_naive_bjt(dt).strftime("%Y-%m-%d %H:%M:%S")

    now = datetime.now(timezone.utc)
    if start_time is None:
        start_time = _norm_bound_time(now - timedelta(hours=24))
    else:
        start_time = _norm_bound_time(start_time)
    if end_time is None:
        end_time = _norm_bound_time(now)
    else:
        end_time = _norm_bound_time(end_time)
    
    type_filter = None
    if event_types:
        type_filter = event_types.split(',')
    
    events = []
    
    # 1. 设备离线/恢复事件 —— 与上一轮巡检结果对比的「状态变化」
    # 旧实现把时间窗内每条巡检快照都当事件（同设备每轮各一条，巡检运行后刷屏）；
    # 新实现用 LAG 窗口函数取同设备上一轮 is_online，仅保留状态翻转的记录。
    # prev 为 NULL（该设备首轮巡检）时比较结果为 NULL 被过滤，首轮不产生事件。
    prev_online = func.lag(InspectionDeviceResult.is_online).over(
        partition_by=InspectionDeviceResult.device_id,
        order_by=InspectionDeviceResult.scanned_at,
    ).label('prev_online')

    insp_subq = (
        select(
            InspectionDeviceResult.id.label('event_id'),
            InspectionDeviceResult.device_id.label('device_id'),
            InspectionDeviceResult.is_online.label('is_online'),
            prev_online,
            InspectionDeviceResult.sys_name.label('sys_name'),
            InspectionDeviceResult.error_message.label('error_message'),
            InspectionDeviceResult.scanned_at.label('scanned_at'),
        )
    ).subquery()

    insp_base_cols = (
        insp_subq.c.event_id,
        insp_subq.c.device_id,
        insp_subq.c.sys_name,
        insp_subq.c.error_message,
        insp_subq.c.scanned_at,
        Device.name.label('resource_name'),
    )

    # 离线事件：上一轮在线 → 本轮离线
    insp_query = (
        select(*insp_base_cols)
        .join(Device, insp_subq.c.device_id == Device.id)
        .where(and_(
            insp_subq.c.is_online == False,
            insp_subq.c.prev_online == True,
            insp_subq.c.scanned_at >= start_time,
            insp_subq.c.scanned_at <= end_time,
        ))
    )

    insp_result = await db.execute(insp_query)
    for row in insp_result.all():
        resource_name = row.sys_name if row.sys_name else row.resource_name
        if not type_filter or "device_offline" in type_filter:
            events.append({
                "id": f"insp_{row.event_id}",
                "event_type": "device_offline",
                "severity": "error",
                "title": f"{resource_name} 设备离线",
                "description": row.error_message or "设备无响应",
                "resource_type": "device",
                "resource_id": row.device_id,
                "resource_name": resource_name,
                "occurred_at": row.scanned_at.isoformat() if row.scanned_at else None,
                "detail_url": f"/devices/{row.device_id}" if row.device_id else None,
                "source": "巡检"
            })

    # 恢复事件：上一轮离线 → 本轮在线
    insp_online_query = (
        select(*insp_base_cols)
        .join(Device, insp_subq.c.device_id == Device.id)
        .where(and_(
            insp_subq.c.is_online == True,
            insp_subq.c.prev_online == False,
            insp_subq.c.scanned_at >= start_time,
            insp_subq.c.scanned_at <= end_time,
        ))
    )

    insp_online_result = await db.execute(insp_online_query)
    for row in insp_online_result.all():
        resource_name = row.sys_name if row.sys_name else row.resource_name
        if not type_filter or "device_online" in type_filter:
            events.append({
                "id": f"insp_online_{row.event_id}",
                "event_type": "device_online",
                "severity": "info",
                "title": f"{resource_name} 设备恢复在线",
                "description": "设备恢复在线",
                "resource_type": "device",
                "resource_id": row.device_id,
                "resource_name": resource_name,
                "occurred_at": row.scanned_at.isoformat() if row.scanned_at else None,
                "detail_url": f"/devices/{row.device_id}" if row.device_id else None,
                "source": "巡检"
            })
    
    # 2. 备份成功/失败/配置变更事件（join 一次取设备名，替代旧实现的逐条 N+1 查询）
    backup_query = (
        select(
            Backup.id.label('backup_id'),
            Backup.device_id.label('device_id'),
            Backup.status.label('status'),
            Backup.has_change.label('has_change'),
            Backup.change_summary.label('change_summary'),
            Backup.error_message.label('error_message'),
            Backup.created_at.label('created_at'),
            Device.name.label('device_name'),
        )
        .outerjoin(Device, Backup.device_id == Device.id)
        .where(and_(
            Backup.created_at >= start_time,
            Backup.created_at <= end_time
        ))
    )

    backup_result = await db.execute(backup_query)
    for row in backup_result.all():
        device_name = row.device_name or f"Device {row.device_id}"

        if row.status == "failed":
            if not type_filter or "backup_fail" in type_filter:
                events.append({
                    "id": f"backup_{row.backup_id}",
                    "event_type": "backup_fail",
                    "severity": "error",
                    "title": f"{device_name} 备份失败",
                    "description": row.error_message or "备份过程发生错误",
                    "resource_type": "device",
                    "resource_id": row.device_id,
                    "resource_name": device_name,
                    "occurred_at": row.created_at.isoformat() if row.created_at else None,
                    "detail_url": f"/devices/{row.device_id}" if row.device_id else None,
                    "source": "备份"
                })
        elif row.status == "success":
            if row.has_change:
                if not type_filter or "config_change" in type_filter:
                    events.append({
                        "id": f"backup_change_{row.backup_id}",
                        "event_type": "config_change",
                        "severity": "warning",
                        "title": f"{device_name} 配置发生变更",
                        "description": row.change_summary or "检测到配置变化",
                        "resource_type": "device",
                        "resource_id": row.device_id,
                        "resource_name": device_name,
                        "occurred_at": row.created_at.isoformat() if row.created_at else None,
                        "detail_url": f"/devices/{row.device_id}" if row.device_id else None,
                        "source": "备份"
                    })
            elif not type_filter or "backup_success" in type_filter:
                events.append({
                    "id": f"backup_{row.backup_id}",
                    "event_type": "backup_success",
                    "severity": "info",
                    "title": f"{device_name} 备份成功",
                    "description": "配置备份完成，无变更",
                    "resource_type": "device",
                    "resource_id": row.device_id,
                    "resource_name": device_name,
                    "occurred_at": row.created_at.isoformat() if row.created_at else None,
                    "detail_url": f"/devices/{row.device_id}" if row.device_id else None,
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