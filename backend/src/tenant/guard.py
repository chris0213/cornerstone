"""租户状态守卫：停用/删除的租户不得再登录。

与「显式拒绝 + 明确提示」的产品口径一致，不做静默降级；停用租户时
由租户管理接口回收其全部登录会话，已有 token 也会因会话撤销而失效。
"""
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tenant import Tenant


async def ensure_tenant_active(db: AsyncSession, tenant_id: int) -> None:
    """校验租户存在且为启用状态；否则抛出 403 并给出可读原因。"""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="所属租户不存在或已删除，请联系平台管理员",
        )
    if tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="所属租户已停用，请联系平台管理员",
        )
