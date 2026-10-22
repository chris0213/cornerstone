from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, delete, update, func

from ..database import get_db
from ..models import Role, Permission, RolePermission, User, AuditLog
from ..schemas import RoleResponse, PermissionResponse, UserRoleUpdate
from ..utils.ip_whitelist import get_client_ip_from_request
from .dependencies import get_current_active_user, get_current_superuser, require_permission

router = APIRouter()


def role_conflict(code: str, message: str, **params) -> HTTPException:
    """结构化 409：detail.code 供前端 i18n 映射（与 knowledge 409 惯例一致）。"""
    return HTTPException(
        status_code=409,
        detail={"code": code, "message": message, "params": params},
    )


async def _audit(db: AsyncSession, request: Request, username: str, action: str, detail: str, success: str = "true"):
    """写角色管理审计日志（不提交，由调用方统一 commit）。"""
    await db.execute(insert(AuditLog).values(
        user=username,
        action=action,
        resource="角色",
        detail=detail,
        ip_address=get_client_ip_from_request(request) if request else None,
        success=success,
    ))


async def _count_builtin_active_superusers(db: AsyncSession) -> int:
    """统计启用状态的超级管理员数量。"""
    result = await db.execute(
        select(func.count(User.id)).where(User.is_superuser == True, User.is_active == True)  # noqa: E712
    )
    return result.scalar_one()


@router.get("/roles", response_model=list[RoleResponse])
async def get_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:read"))
):
    result = await db.execute(select(Role))
    return result.scalars().all()

@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:read"))
):
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role

@router.post("/roles", response_model=RoleResponse)
async def create_role(
    role: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:write"))
):
    result = await db.execute(select(Role).where(Role.name == role["name"]))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Role already exists")

    stmt = insert(Role).values(
        name=role["name"],
        display_name=role.get("display_name") or role["name"],
        description=role.get("description", ""),
    ).returning(Role)
    result = await db.execute(stmt)
    new_role = result.scalar_one()

    await _audit(db, request, current_user.username, "创建角色",
                 f"创建角色 {new_role.display_name} ({new_role.name})")
    await db.commit()
    return new_role

@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:delete"))
):
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # 内置角色禁止删除
    if role.is_builtin:
        raise role_conflict(
            "system.roleBuiltin",
            f"内置角色「{role.display_name or role.name}」不允许删除",
            name=role.name,
        )

    # 角色仍被用户使用时禁止删除（避免用户被置为无角色）
    count_result = await db.execute(
        select(func.count(User.id)).where(User.role_id == role_id)
    )
    user_count = count_result.scalar_one()
    if user_count > 0:
        raise role_conflict(
            "system.roleInUse",
            f"角色「{role.display_name or role.name}」仍有 {user_count} 个用户使用，不允许删除",
            count=user_count,
        )

    await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    await db.execute(delete(Role).where(Role.id == role_id))
    await _audit(db, request, current_user.username, "删除角色",
                 f"删除角色 {role.display_name or role.name} ({role.name})")
    await db.commit()

@router.get("/permissions", response_model=list[PermissionResponse])
async def get_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:read"))
):
    result = await db.execute(select(Permission))
    return result.scalars().all()

@router.post("/users/{user_id}/roles", status_code=204)
async def assign_role_to_user(
    user_id: int,
    role_update: UserRoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:write"))
):
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(select(Role).where(Role.id == role_update.role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # User 用单一 role_id 关联角色，重复分配时返回 400
    result = await db.execute(
        select(User).where(User.id == user_id, User.role_id == role_update.role_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Role already assigned")

    # 不允许修改自己的角色
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")

    # 不允许改动最后一个启用状态超级管理员的角色（防止移除 super_admin 或降权）
    if target_user.is_superuser and target_user.is_active:
        superuser_count = await _count_builtin_active_superusers(db)
        if superuser_count <= 1 and role.name != "super_admin":
            raise HTTPException(status_code=400, detail="系统必须保留至少一个启用状态的超级管理员")

    await db.execute(update(User).where(User.id == user_id).values(role_id=role_update.role_id))

    result = await db.execute(select(User).where(User.id == user_id))
    updated_user = result.scalar_one()
    await _audit(db, request, current_user.username, "分配角色",
                 f"将用户 {updated_user.username} 的角色设置为 {role.display_name or role.name}")
    await db.commit()

@router.delete("/users/{user_id}/roles/{role_id}", status_code=204)
async def remove_role_from_user(
    user_id: int,
    role_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:write"))
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.role_id == role_id)
    )
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User role not found")

    # 不允许移除自己的角色
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能移除自己的角色")

    # 最后一个启用状态超级管理员不允许被移除角色
    if target_user.is_superuser and target_user.is_active:
        superuser_count = await _count_builtin_active_superusers(db)
        if superuser_count <= 1:
            raise HTTPException(status_code=400, detail="系统必须保留至少一个启用状态的超级管理员")

    await db.execute(update(User).where(User.id == user_id).values(role_id=None))

    await _audit(db, request, current_user.username, "移除角色",
                 f"移除用户 {target_user.username} 的角色")
    await db.commit()

@router.get("/users/{user_id}/permissions", response_model=list[str])
async def get_user_permissions(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:read"))
):
    from ..services.permission_service import get_user_permissions as get_perms
    return await get_perms(db, user_id)

@router.get("/users/{user_id}/roles", response_model=list[str])
async def get_user_roles(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:read"))
):
    from ..services.permission_service import get_user_roles as get_roles
    return await get_roles(db, user_id)
