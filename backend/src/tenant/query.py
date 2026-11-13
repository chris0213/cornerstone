"""租户查询辅助：显式条件与活跃租户遍历。

ORM SELECT 已由 `do_orm_execute` 统一注入租户条件，正常情况下无需手动加；
`tenant_filter` 用于必须手写条件的场景（后台任务、原生/拼接 SQL）作为兜底。
"""
from typing import List

from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tenant import Tenant
from .context import current_tenant_id


def tenant_filter(model):
    """当前上下文的租户条件；无上下文（系统作用域）时返回恒真条件。"""
    tenant_id = current_tenant_id()
    if tenant_id is None:
        return true()
    return model.tenant_id == tenant_id


async def get_active_tenant_ids(db: AsyncSession) -> List[int]:
    """全部活跃租户 ID（Tenant 是平台级实体，本身不参与行级过滤）。"""
    result = await db.execute(
        select(Tenant.id)
        .where(Tenant.status == "active", Tenant.deleted_at.is_(None))
        .order_by(Tenant.id)
    )
    return list(result.scalars().all())
