"""租户管理 API（仅平台超管）。

- 列表：编码/名称/状态/创建时间/用户数；
- 新建：编码必填且全局唯一；
- 启用/停用：默认租户不允许停用；停用时回收该租户全部登录会话，
  并由登录守卫拒绝其用户后续登录（见 `src.tenant.guard`）；
- 所有变更写审计日志。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AuditLog, Tenant, User, UserSession
from ..tenant.bootstrap import DEFAULT_TENANT_ID
from ..tenant.context import system_scope
from ..utils.ip_whitelist import get_client_ip_from_request
from .dependencies import require_permission

router = APIRouter()

TENANT_STATUSES = {"active", "suspended"}


class TenantCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50, description="租户编码，全局唯一")
    name: str = Field(..., min_length=1, max_length=100, description="租户名称")
    plan: str = Field("standard", max_length=50)
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        code = (value or "").strip().lower()
        if not code:
            raise ValueError("租户编码不能为空")
        return code


class TenantStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = Field(None, max_length=200)


async def _user_counts(db: AsyncSession) -> dict:
    with system_scope():
        rows = await db.execute(select(User.tenant_id, func.count(User.id)).group_by(User.tenant_id))
        return {tenant_id: count for tenant_id, count in rows.all()}


def _serialize(tenant: Tenant, user_count: int) -> dict:
    return {
        "id": tenant.id,
        "code": tenant.code,
        "name": tenant.name,
        "status": tenant.status,
        "plan": tenant.plan,
        "description": tenant.description,
        "created_at": tenant.created_at,
        "user_count": user_count,
        "is_default": tenant.id == DEFAULT_TENANT_ID,
    }


async def _get_tenant(db: AsyncSession, tenant_id: int) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="租户不存在")
    return tenant


@router.get("", dependencies=[Depends(require_permission("system:admin"))])
@router.get("/", include_in_schema=False, dependencies=[Depends(require_permission("system:admin"))])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    """租户列表（仅平台超管）。"""
    with system_scope():
        tenants = (
            await db.execute(
                select(Tenant).where(Tenant.deleted_at.is_(None)).order_by(Tenant.id)
            )
        ).scalars().all()
    counts = await _user_counts(db)
    return [_serialize(t, counts.get(t.id, 0)) for t in tenants]


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", include_in_schema=False, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system:admin")),
):
    """新建租户：编码必填且全局唯一。"""
    existing = (
        await db.execute(select(Tenant).where(Tenant.code == payload.code))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="租户编码已存在")

    tenant = Tenant(
        code=payload.code,
        name=payload.name.strip(),
        plan=payload.plan or "standard",
        description=payload.description,
        status="active",
    )
    db.add(tenant)
    await db.flush()

    db.add(AuditLog(
        user=current_user.username,
        action="创建租户",
        resource="租户",
        detail=f"创建租户 {tenant.code}（{tenant.name}）",
        ip_address=get_client_ip_from_request(request),
        success="true",
    ))
    await db.commit()
    await db.refresh(tenant)
    return _serialize(tenant, 0)


@router.put("/{tenant_id}/status")
async def update_tenant_status(
    tenant_id: int,
    payload: TenantStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system:admin")),
):
    """启用/停用租户。停用会回收该租户全部登录会话。"""
    if payload.status not in TENANT_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态只能是 active 或 suspended")

    tenant = await _get_tenant(db, tenant_id)
    if tenant.id == DEFAULT_TENANT_ID and payload.status == "suspended":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="默认租户不允许停用")

    changed = tenant.status != payload.status
    tenant.status = payload.status

    revoked = 0
    if payload.status == "suspended" and changed:
        # 停用即强制下线：仅拦登录不足以收回已签发 token，这里撤销现有会话
        with system_scope():
            result = await db.execute(
                update(UserSession)
                .where(
                    UserSession.user_id.in_(
                        select(User.id).where(User.tenant_id == tenant_id)
                    )
                )
                .values(is_revoked=True)
            )
            revoked = result.rowcount or 0

    if changed:
        action = "启用租户" if payload.status == "active" else "停用租户"
        detail = f"{action} {tenant.code}（{tenant.name}）"
        if payload.reason:
            detail += f"，原因：{payload.reason}"
        if revoked:
            detail += f"，已强制下线会话 {revoked} 个"
        db.add(AuditLog(
            user=current_user.username,
            action=action,
            resource="租户",
            detail=detail,
            ip_address=get_client_ip_from_request(request),
            success="true",
        ))

    await db.commit()
    await db.refresh(tenant)
    counts = await _user_counts(db)
    return _serialize(tenant, counts.get(tenant.id, 0))
