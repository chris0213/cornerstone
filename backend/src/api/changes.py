"""变更管理 API（全局变更审计视图）

聚合两类变更来源，统一时间线/表格查询：
- circuit_changes：专线字段级变更（create/update/delete + 旧值/新值，batch_id 聚合同次操作）
- backups：配置备份变更（has_change=1 的成功备份，摘要即变更说明）

列表按「操作批次」聚合返回：同一次多字段编辑折叠为一条记录（items 内含明细），
统计与列表口径一致（按批次计数），支持分页 total 与 CSV 全量导出。
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, union_all, func, and_, or_, String
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Circuit, CircuitChange, Device, Backup
from ..utils.logger import audit_log
from ..utils.ip_whitelist import get_client_ip_from_request
from .dependencies import (
    PageParams, pagination, require_permission, get_current_active_user,
)

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
    change_type/field/old_value/new_value/operator/remark/batch_id/created_at）"""
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
            CircuitChange.batch_id.label("batch_id"),
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
            func.cast("", type_=CircuitChange.batch_id.type).label("batch_id"),
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


# 批次键：circuit 有 batch_id 用 batch_id；config/无批次的存量行用「source-id」独立成批
def _batch_key_expr(sub):
    """SQL 侧批次键：有 batch_id 用 b:{batch_id}，否则用 s:{source}-{id}（与 _batch_key 一致）"""
    return func.coalesce(
        "b:" + func.nullif(sub.c.batch_id, ""),
        "s:" + sub.c.source + "-" + func.cast(sub.c.id, String),
    )


def _batch_key(row) -> str:
    if row.batch_id:
        return f"b:{row.batch_id}"
    return f"s:{row.source}-{row.id}"


def _serialize_row(row) -> dict:
    return {
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
        "batch_id": row.batch_id or "",
        "created_at": row.created_at,
    }


def _group_batches(rows) -> list[dict]:
    """把字段级行聚合为操作批次：同批次取首条时间/操作人，明细收进 changes 数组"""
    groups: dict[str, list] = {}
    order: list[str] = []
    for row in rows:
        key = _batch_key(row)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    result = []
    for key in order:
        batch_rows = groups[key]
        first = batch_rows[0]
        item = _serialize_row(first)
        # 批次聚合字段：字段级明细
        item["changes"] = [
            {
                "field": r.field or "",
                "old_value": r.old_value or "",
                "new_value": r.new_value or "",
            }
            for r in batch_rows
        ]
        item["field_count"] = len(batch_rows)
        result.append(item)
    return result


@router.get("")
async def list_changes(
    source: Optional[str] = Query(None, description="来源：circuit=专线变更 / config=配置变更"),
    object_id: Optional[int] = Query(None, description="对象ID（专线或设备）"),
    change_type: Optional[str] = Query(None, description="变更类型：create/update/delete"),
    operator: Optional[str] = Query(None, description="操作人（模糊）"),
    keyword: Optional[str] = Query(None, description="关键词（对象名/字段/新旧值）"),
    start: Optional[datetime] = Query(None, description="起始时间（含）"),
    end: Optional[datetime] = Query(None, description="结束时间（不含）"),
    page: PageParams = Depends(pagination(default_limit=50, max_limit=500)),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("logs:read")),
):
    """变更列表（按操作批次聚合，时间倒序；total 为批次条数）"""
    sub = _union_subquery()
    row_conditions = _row_conditions(sub, source, object_id, operator, keyword, start, end)
    batch_key = _batch_key_expr(sub)

    if change_type:
        # 批次级筛选：批次内任一行命中 change_type，则整批保留
        matched = select(batch_key.label("bk")).where(
            and_(*row_conditions, sub.c.change_type == change_type)
        )
        stmt = select(sub).where(batch_key.in_(select(matched.subquery().c.bk)))
        total_stmt = select(func.count()).select_from(
            select(batch_key.label("bk")).where(
                batch_key.in_(select(matched.subquery().c.bk))
            ).group_by(batch_key).subquery()
        )
    elif row_conditions:
        stmt = select(sub).where(and_(*row_conditions))
        total_stmt = select(func.count()).select_from(
            select(batch_key.label("bk")).where(and_(*row_conditions)).group_by(batch_key).subquery()
        )
    else:
        stmt = select(sub)
        total_stmt = select(func.count()).select_from(
            select(batch_key.label("bk")).group_by(batch_key).subquery()
        )

    total = (await db.execute(total_stmt)).scalar() or 0

    stmt = stmt.order_by(sub.c.created_at.desc()).offset(page.skip).limit(page.limit)
    rows = (await db.execute(stmt)).all()

    return {
        "items": _group_batches(rows),
        "total": total,
        "skip": page.skip,
        "limit": page.limit,
    }


def _row_conditions(sub, source, object_id, operator, keyword, start, end):
    """行级过滤条件（用于批次聚合前的筛选）"""
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
    return conditions


@router.get("/operators")
async def changes_operators(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("logs:read")),
):
    """操作人下拉选项（去重）"""
    sub = _union_subquery()
    stmt = select(sub.c.operator).where(sub.c.operator.isnot(None), sub.c.operator != "").distinct()
    rows = (await db.execute(stmt)).all()
    return sorted({r[0] for r in rows})


@router.get("/export")
async def export_changes(
    source: Optional[str] = Query(None),
    object_id: Optional[int] = Query(None),
    operator: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
    current_user=Depends(require_permission("logs:read")),
):
    """按当前筛选条件导出全量变更（JSON 行，前端转 CSV；上限 10000 条）"""
    sub = _union_subquery()
    stmt = select(sub)
    stmt = _apply_filters(stmt, sub, source, object_id, operator, keyword, start, end)
    stmt = stmt.order_by(sub.c.created_at.desc()).limit(10000)
    rows = (await db.execute(stmt)).all()

    await audit_log(
        db, current_user.id, "changes", 0, "export",
        {"count": len(rows), "source": source or "all"},
        get_client_ip_from_request(request) if request else None
    )

    return {"items": [_serialize_row(r) for r in rows], "count": len(rows)}


@router.get("/summary")
async def changes_summary(
    start: Optional[datetime] = Query(None, description="起始时间（含），缺省本月"),
    end: Optional[datetime] = Query(None, description="结束时间（不含），缺省下月"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("logs:read")),
):
    """变更统计（默认本月，按操作批次计数，口径与列表一致）"""
    if not start or not end:
        start, end = _month_range()

    sub = _union_subquery()
    stmt = _apply_filters(select(sub), sub, None, None, None, None, start, end)

    rows = (await db.execute(stmt)).all()

    # 按批次分组后计数，与列表聚合口径一致
    batch_keys = [_batch_key(r) for r in rows]
    total = len(set(batch_keys))

    circuit_batches = {k for k, r in zip(batch_keys, rows) if r.source == "circuit"}
    config_batches = {k for k, r in zip(batch_keys, rows) if r.source == "config"}
    object_count = len({(r.source, r.object_id) for r in rows})

    return {
        "total": total,
        "circuit_count": len(circuit_batches),
        "config_count": len(config_batches),
        "object_count": object_count,
        "start": start,
        "end": end,
    }
