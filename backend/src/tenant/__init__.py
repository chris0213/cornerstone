"""多租户地基：请求上下文、模型 mixin、ORM 会话钩子。"""
from .context import (
    TenantContext,
    current_tenant_id,
    reset_tenant,
    set_tenant,
    system_scope,
    tenant_scope,
)
from .mixin import TenantMixin
from .session import CrossTenantWriteError

__all__ = [
    "TenantContext",
    "current_tenant_id",
    "reset_tenant",
    "set_tenant",
    "system_scope",
    "tenant_scope",
    "TenantMixin",
    "CrossTenantWriteError",
]
