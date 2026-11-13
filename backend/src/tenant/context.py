"""请求级租户上下文。

设计要点（对应多租户方案 §3.4 第 1 层）：

- 认证依赖 `get_current_user` 解析出用户后调用 `set_tenant()` 写入 ContextVar；
- HTTP 入口用 `tenant_scope`/**中间件**兜底复位，避免上下文串请求；
- 无上下文表示“系统级执行”（登录校验、后台任务、种子数据、测试），此时
  不做行级过滤；需要显式跨租户时用 `system_scope()`。
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class TenantContext:
    tenant_id: Optional[int]      # None 表示系统级（不过滤）
    user_id: Optional[int] = None
    bypass: bool = False          # True 表示显式跨租户/系统操作


_ctx: ContextVar[Optional[TenantContext]] = ContextVar("tenant_context", default=None)


def set_tenant(
    tenant_id: Optional[int],
    user_id: Optional[int] = None,
    bypass: bool = False,
) -> Token:
    """写入当前上下文，返回可用于 `reset_tenant` 的 token。"""
    return _ctx.set(TenantContext(tenant_id=tenant_id, user_id=user_id, bypass=bypass))


def reset_tenant(token: Token) -> None:
    _ctx.reset(token)


def get_tenant_context() -> Optional[TenantContext]:
    return _ctx.get()


def current_tenant_id() -> Optional[int]:
    """返回需要过滤的租户 ID；None 表示当前不做行级过滤。"""
    ctx = _ctx.get()
    if ctx is None or ctx.bypass:
        return None
    return ctx.tenant_id


def current_user_id() -> Optional[int]:
    ctx = _ctx.get()
    return ctx.user_id if ctx else None


@contextmanager
def tenant_scope(tenant_id: int, user_id: Optional[int] = None) -> Iterator[None]:
    """在代码块内以指定租户执行（后台任务/运维脚本/测试用）。"""
    token = set_tenant(tenant_id, user_id)
    try:
        yield
    finally:
        reset_tenant(token)


@contextmanager
def system_scope() -> Iterator[None]:
    """显式声明系统级执行：跳过行级过滤（种子数据、登录、清理任务等）。"""
    token = set_tenant(None, bypass=True)
    try:
        yield
    finally:
        reset_tenant(token)
