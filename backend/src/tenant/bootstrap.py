"""默认租户初始化。

生产环境由 Alembic 迁移创建 `id=1, code='default'` 的默认租户；
测试库（`Base.metadata.create_all`）与空库首次启动时由这里补齐。
"""
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tenant import Tenant

DEFAULT_TENANT_ID = 1
DEFAULT_TENANT_CODE = "default"
DEFAULT_TENANT_NAME = "默认租户"


async def ensure_default_tenant(session: AsyncSession) -> Tenant:
    tenant = await session.get(Tenant, DEFAULT_TENANT_ID)
    if tenant is not None:
        return tenant

    result = await session.execute(select(Tenant).where(Tenant.code == DEFAULT_TENANT_CODE))
    tenant = result.scalar_one_or_none()
    if tenant is not None:
        return tenant

    tenant = Tenant(
        id=DEFAULT_TENANT_ID,
        code=DEFAULT_TENANT_CODE,
        name=DEFAULT_TENANT_NAME,
        status="active",
    )
    session.add(tenant)
    await session.flush()

    # 显式指定 id 后修正 PG 序列，避免后续插入主键冲突
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await session.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('tenants','id'), "
                "GREATEST((SELECT MAX(id) FROM tenants), 1))"
            )
        )

    await session.commit()
    return tenant
