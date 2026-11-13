"""ORM 会话级租户过滤与写入兜底（方案 §3.4 第 2、3 层）。

- `do_orm_execute`：给所有继承 `TenantMixin` 的实体 SELECT 自动追加
  `with_loader_criteria`，同时覆盖 joinedload/selectinload 等关系加载；
- `before_flush`：新对象 tenant_id 为空时按上下文补齐，显式跨租户写入抛异常，
  已存在对象禁止修改 tenant_id。

无租户上下文（登录校验、后台任务、种子数据、测试直连）时不做过滤，等价于
系统级执行；需要显式跳过时可传 `execution_options(include_all_tenants=True)`
或使用 `system_scope()`。
"""
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, with_loader_criteria

from .context import current_tenant_id
from .mixin import TenantMixin


class CrossTenantWriteError(RuntimeError):
    """当前租户上下文与写入对象的 tenant_id 不一致。"""


@event.listens_for(Session, "do_orm_execute")
def _add_tenant_criteria(execute_state) -> None:
    if not execute_state.is_select or execute_state.is_column_load:
        return
    if execute_state.execution_options.get("include_all_tenants"):
        return
    tenant_id = current_tenant_id()
    if tenant_id is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_and_guard_tenant(session: Session, flush_context, instances) -> None:
    tenant_id = current_tenant_id()
    if tenant_id is None:
        return

    for obj in session.new:
        if not isinstance(obj, TenantMixin):
            continue
        current = getattr(obj, "tenant_id", None)
        if current is None:
            obj.tenant_id = tenant_id
        elif current != tenant_id:
            raise CrossTenantWriteError(
                f"跨租户写入被拒绝：{type(obj).__name__}.tenant_id={current}，"
                f"当前上下文租户={tenant_id}"
            )

    for obj in session.dirty:
        if not isinstance(obj, TenantMixin):
            continue
        if not session.is_modified(obj, include_collections=False):
            continue
        history = inspect(obj).attrs.tenant_id.history
        if history.has_changes():
            raise CrossTenantWriteError(
                f"禁止修改 tenant_id：{type(obj).__name__} 不允许从一个租户迁移到另一个租户"
            )
