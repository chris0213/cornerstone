"""变更管理 API（全局变更审计视图）

聚合两类变更来源，统一时间线/表格查询：
- circuit_changes：专线字段级变更（create/update/delete + 旧值/新值）
- backups：配置备份变更（has_change=1 的成功备份，摘要即变更说明）
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, union_all, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Circuit, CircuitChange, Device, Backup
from .auth import get_current_active_user
from .dependencies import PageParams, pagination

router = APIRouter()

BEIJING_TZ = timezone(timedelta(hours=8))


def _month_range(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """本月时间范围（北京时间的自然月）"""
    bj = now.astimezone(BEIJING_TZ) if now else datetime.now(BEIJING_TZ)
    start = datetime(bj.year, bj.month, 1)
    end = (datetime(bj.year + 1, 1, 1) if bj.month == 12
           else datetime(bj.year, bj.month + 1, 1))
    return start, end


def _union_subquery():
    """专线变更 + 配置变更的统一子查询（列对齐：id/source/object_id/object_name/
    change_type/field/old_value/new_value/operator/remark/created_at）"""
    circuit_q = (
        select(
            CircuitChange.id.label("id"),
            func.cast("circuit", type_=CircuitChange.change_type.type).label("source"),
            CircuitChange.circuit_id.label("object_id"),
            Circuit.name.label("object_name"),
            CircuitChange.change_type.label("change_type"),
            CircuitChange.field_name.label("field"),
            CircuitChange.old_value.label("old_value"),
            CircuitChange.new_value.label("new_value"),
            CircuitChange.operator.label("operator"),
            CircuitChange.remark.label("remark"),
            CircuitChange.created_at.label("created_at"),
        )
        .outerjoin(Circuit, CircuitChange.circuit_id == Circuit.id)
    )

    config_q = (
        select(
            Backup.id.label("id"),
            func.cast("config", type_=CircuitChange.change_type.type).label("source"),
            Backup.device_id.label("object_id"),
            Device.name.label("object_name"),
            func.cast("update", type_=CircuitChange.change_type.type).label("change_type"),
            func.cast("配置内容", type_=CircuitChange.field_name.type).label("field"),
            func.cast("", type_=CircuitChange.old_value.type).label("old_value"),
            func.coalesce(Backup.change_summary, "").label("new_value"),
            Backup.operator.label("operator"),
            func.cast("", type_=CircuitChange.remark.type).label("remark"),
            Backup.created_at.label("created_at"),
        )
        .select_from(Backup)
        .outerjoin(Device, Backup.device_id == Device.id)
        .where(and_(Backup.has_change.is_(True), Backup.status == "success"))
    )

    return union_all(circuit_q, config_q).subquery()


def _apply_filters(stmt, sub, source, object_id, operator, keyword, start, end):
    conditions = []
    if source:
        conditions.append(sub.c.source == source)
    if object_id is not None:
        conditions.append(sub.c.object_id == object_id)
    if operator:
        conditions.append(sub.c.operator.ilike(f"%{operator}%"))
    if keyword:
        like = f"%{keyword}%"
        conditions.append(or_(
            sub.c.object_name.ilike(like),
            sub.c.field.ilike(like),
            sub.c.new_value.ilike(like),
            sub.c.old_value.ilike(like),
        ))
    if start:
        conditions.append(sub.c.created_at >= start)
    if end:
        conditions.append(sub.c.created_at < end)
    return stmt.where(and_(*conditions)) if conditions else stmt


@router.get("")
async def list_changes(
    source: Optional[str] = Query(None, description="来源：circuit=专线变更 / config=配置变更"),
    object_id: Optional[int] = Query(None, description="对象ID（专线或设备）"),
    operator: Optional[str] = Query(None, description="操作人（模糊）"),
    keyword: Optional[str] = Query(None, description="关键词（对象名/字段/新旧值）"),
    start: Optional[datetime] = Query(None, description="起始时间（含）"),
    end: Optional[datetime] = Query(None, description="结束时间（不含）"),
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """变更列表（时间倒序，支持来源/对象/操作人/关键词/时间筛选）"""
    sub = _union_subquery()
    stmt = select(sub)
    stmt = _apply_filters(stmt, sub, source, object_id, operator, keyword, start, end)
    stmt = stmt.order_by(sub.c.created_at.desc()).offset(page.skip).limit(page.limit)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": f"{row.source}-{row.id}",
            "source": row.source,
            "object_id": row.object_id,
            "object_name": row.object_name or "",
            "change_type": row.change_type or "update",
            "field": row.field or "",
            "old_value": row.old_value or "",
            "new_value": row.new_value or "",
            "operator": row.operator or "",
            "remark": row.remark or "",
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/summary")
async def changes_summary(
    start: Optional[datetime] = Query(None, description="起始时间（含），缺省本月"),
    end: Optional[datetime] = Query(None, description="结束时间（不含），缺省下月"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """变更统计（默认本月：总数/专线变更/配置变更/受影响对象数）"""
    if not start or not end:
        start, end = _month_range()

    sub = _union_subquery()
    stmt = _apply_filters(select(sub), sub, None, None, None, None, start, end)

    rows = (await db.execute(stmt)).all()
    circuit_count = sum(1 for r in rows if r.source == "circuit")
    config_count = sum(1 for r in rows if r.source == "config")
    object_count = len({(r.source, r.object_id) for r in rows})

    return {
        "total": len(rows),
        "circuit_count": circuit_count,
        "config_count": config_count,
        "object_count": object_count,
        "start": start,
        "end": end,
    }
