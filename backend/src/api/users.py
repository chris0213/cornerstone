from datetime import datetime, timezone
import random
import string
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.orm import joinedload

from ..database import get_db
from ..models import User, Role, Permission, RolePermission, UserSession, AuditLog
from ..schemas import UserCreate, UserUpdate, UserResponse, ResetPasswordResponse, UserSessionResponse, RoleResponse, RoleCreate, PermissionResponse
from ..utils.security import get_password_hash, validate_password
from ..utils.ip_whitelist import get_client_ip_from_request
from .dependencies import get_current_active_user, get_current_superuser, PageParams, pagination

router = APIRouter()

# 用户设置相关 Schema
class UserSettingsResponse(BaseModel):
    locale: str

class UserSettingsUpdate(BaseModel):
    locale: Optional[str] = None

def generate_random_password(length: int = 8) -> str:
    """生成随机密码：包含大小写字母和数字"""
    chars = string.ascii_letters + string.digits
    password = ''.join(random.choice(chars) for _ in range(length))
    # 确保至少包含一个大写、一个小写和一个数字
    if not any(c.isupper() for c in password):
        password = password[:-1] + random.choice(string.ascii_uppercase)
    if not any(c.islower() for c in password):
        password = password[:-1] + random.choice(string.ascii_lowercase)
    if not any(c.isdigit() for c in password):
        password = password[:-1] + random.choice(string.digits)
    return password

async def build_user_response(db: AsyncSession, user: User) -> UserResponse:
    """构建用户响应对象，包含角色和权限信息"""
    # 获取角色信息
    stmt = select(Role).where(Role.id == user.role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    
    # 获取权限列表
    stmt = select(Permission).join(
        RolePermission, RolePermission.permission_id == Permission.id
    ).where(RolePermission.role_id == (user.role_id or 0))
    result = await db.execute(stmt)
    permissions = result.scalars().all()
    
    role_name = ""
    role_display_name = ""
    if role:
        role_name = role.name
        role_display_name = role.display_name or role.name
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name or user.username,
        role=role_name,
        role_display_name=role_display_name,
        permissions=[f"{p.module}:{p.action}" for p in permissions],
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        is_sso_user=user.is_sso_user,
        last_login_at=user.last_login_at,
        last_login_ip=user.last_login_ip,
        avatar=user.avatar,
        created_at=user.created_at,
        updated_at=user.updated_at
    )

@router.get("/", response_model=list[UserResponse])
async def read_users(
    page: PageParams = Depends(pagination()),
    role: str = None,
    is_active: bool = None,
    keyword: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """获取用户列表（仅super_admin可访问）"""
    stmt = select(User)
    
    if role:
        role_stmt = select(Role.id).where(Role.name == role)
        role_result = await db.execute(role_stmt)
        role_id = role_result.scalar_one_or_none()
        if role_id:
            stmt = stmt.where(User.role_id == role_id)
    
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    
    if keyword:
        stmt = stmt.where(
            (User.username.ilike(f"%{keyword}%")) |
            (User.email.ilike(f"%{keyword}%")) |
            (User.display_name.ilike(f"%{keyword}%"))
        )
    
    result = await db.execute(stmt.offset(page.skip).limit(page.limit))
    users = result.scalars().all()
    
    return [await build_user_response(db, user) for user in users]

@router.get("/{user_id}", response_model=UserResponse)
async def read_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取单个用户信息"""
    # 普通用户只能查看自己，管理员可以查看所有用户
    if not current_user.is_superuser and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="没有足够的权限")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return await build_user_response(db, user)

@router.get("/me/settings", response_model=UserSettingsResponse)
async def get_user_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取当前用户设置"""
    return UserSettingsResponse(locale=current_user.locale or "zh-CN")

@router.put("/me/settings", response_model=UserSettingsResponse)
async def update_user_settings(
    settings: UserSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """更新当前用户设置"""
    update_data = {}
    
    if settings.locale is not None:
        # 验证语言值
        if settings.locale not in ["zh-CN", "en-US"]:
            raise HTTPException(status_code=400, detail="无效的语言设置")
        update_data["locale"] = settings.locale
    
    if update_data:
        stmt = update(User).where(User.id == current_user.id).values(**update_data)
        await db.execute(stmt)
        await db.commit()
        
        # 重新获取用户以获取更新后的值
        result = await db.execute(select(User).where(User.id == current_user.id))
        updated_user = result.scalar_one()
        return UserSettingsResponse(locale=updated_user.locale or "zh-CN")
    
    return UserSettingsResponse(locale=current_user.locale or "zh-CN")

@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """创建用户（仅超级管理员）"""
    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == user.username))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 检查邮箱是否已存在
    result = await db.execute(select(User).where(User.email == user.email))
    existing_email = result.scalar_one_or_none()
    if existing_email:
        raise HTTPException(status_code=400, detail="邮箱已存在")
    
    # 验证密码强度
    if not validate_password(user.password):
        raise HTTPException(status_code=400, detail="密码至少8位，包含字母和数字")
    
    # 获取默认角色（IT运维工程师）
    if not user.role_id:
        role_stmt = select(Role).where(Role.name == "engineer")
        role_result = await db.execute(role_stmt)
        role = role_result.scalar_one_or_none()
        if role:
            user.role_id = role.id
    
    user_data = user.model_dump(exclude={"password"})
    user_data["hashed_password"] = get_password_hash(user.password)
    
    stmt = insert(User).values(**user_data).returning(User)
    result = await db.execute(stmt)
    new_user = result.scalar_one()
    
    client_ip = get_client_ip_from_request(request)
    # 记录审计日志
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="创建用户",
        resource="用户",
        detail=f"创建用户 {new_user.username}",
        ip_address=client_ip,
        success="true"
    )
    await db.execute(stmt)
    
    await db.commit()
    return await build_user_response(db, new_user)

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    request: Request,
    user_id: int,
    user: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """编辑用户"""
    # 普通用户只能更新自己，管理员可以更新所有用户
    if not current_user.is_superuser and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="没有足够的权限")
    
    # 获取用户
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 不允许普通用户修改自己的角色
    if not current_user.is_superuser and user.role_id is not None:
        raise HTTPException(status_code=403, detail="普通用户不能修改角色")
    
    # 不允许非超级管理员将用户设为超级管理员
    if not current_user.is_superuser and user.role_id is not None:
        role_stmt = select(Role).where(Role.id == user.role_id)
        role_result = await db.execute(role_stmt)
        role = role_result.scalar_one_or_none()
        if role and role.name == "super_admin":
            raise HTTPException(status_code=403, detail="只有超级管理员可以分配超级管理员角色")
    
    update_data = user.model_dump(exclude_unset=True)
    
    stmt = update(User).where(User.id == user_id).values(**update_data).returning(User)
    result = await db.execute(stmt)
    updated_user = result.scalar_one_or_none()
    
    # 记录审计日志（脱敏：只记字段名，不记字段值，避免敏感数据进日志）
    if update_data:
        client_ip = get_client_ip_from_request(request)
        stmt = insert(AuditLog).values(
            user=current_user.username,
            action="编辑用户",
            resource="用户",
            detail=f"编辑用户 {updated_user.username}，修改字段: {', '.join(update_data.keys())}",
            ip_address=client_ip,
            success="true"
        )
        await db.execute(stmt)
    
    await db.commit()
    return await build_user_response(db, updated_user)

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """删除用户（仅super_admin可访问）"""
    # 不允许删除自己
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 检查是否是最后一个超级管理员
    if user.is_superuser:
        count_stmt = select(func.count(User.id)).where(
            User.is_superuser == True,
            User.is_active == True
        )
        count_result = await db.execute(count_stmt)
        superuser_count = count_result.scalar_one()
        if superuser_count <= 1:
            raise HTTPException(status_code=400, detail="系统必须保留至少一个启用状态的超级管理员")
    
    # 撤销用户所有会话
    await db.execute(update(UserSession).where(
        UserSession.user_id == user_id
    ).values(is_revoked=True))
    
    client_ip = get_client_ip_from_request(request)
    # 记录审计日志
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="删除用户",
        resource="用户",
        detail=f"删除用户 {user.username}",
        ip_address=client_ip,
        success="true"
    )
    await db.execute(stmt)
    
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()

@router.patch("/{user_id}/toggle", response_model=UserResponse)
async def toggle_user_status(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """启用/停用用户"""
    # 不允许停用自己
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能停用自己")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 检查是否是最后一个超级管理员
    if user.is_superuser:
        count_stmt = select(func.count(User.id)).where(
            User.is_superuser == True,
            User.is_active == True
        )
        count_result = await db.execute(count_stmt)
        superuser_count = count_result.scalar_one()
        if superuser_count <= 1 and user.is_active:
            raise HTTPException(status_code=400, detail="系统必须保留至少一个启用状态的超级管理员")
    
    new_status = not user.is_active
    
    stmt = update(User).where(User.id == user_id).values(is_active=new_status).returning(User)
    result = await db.execute(stmt)
    updated_user = result.scalar_one()
    
    # 如果停用用户，撤销其所有会话
    if not new_status:
        await db.execute(update(UserSession).where(
            UserSession.user_id == user_id
        ).values(is_revoked=True))
    
    client_ip = get_client_ip_from_request(request)
    # 记录审计日志
    status_text = "启用" if new_status else "停用"
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action=f"{status_text}用户",
        resource="用户",
        detail=f"{status_text}用户 {user.username}",
        ip_address=client_ip,
        success="true"
    )
    await db.execute(stmt)
    
    await db.commit()
    return await build_user_response(db, updated_user)

@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """重置用户密码（仅super_admin可访问）"""
    # 不允许重置自己的密码（应使用change-password接口）
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="请使用个人设置中的修改密码功能")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 生成随机密码
    new_password = generate_random_password()
    hashed_password = get_password_hash(new_password)
    
    stmt = update(User).where(User.id == user_id).values(
        hashed_password=hashed_password,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
    ).returning(User)
    result = await db.execute(stmt)
    
    client_ip = get_client_ip_from_request(request)
    # 记录审计日志
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="重置密码",
        resource="用户",
        detail=f"重置用户 {user.username} 的密码",
        ip_address=client_ip,
        success="true"
    )
    await db.execute(stmt)
    
    await db.commit()
    
    return {"message": "密码重置成功", "new_password": new_password}

@router.get("/{user_id}/sessions", response_model=list[UserSessionResponse])
async def get_user_sessions(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """查看用户登录会话列表"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    stmt = select(UserSession).where(UserSession.user_id == user_id).order_by(UserSession.created_at.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    
    return sessions

@router.post("/{user_id}/revoke-sessions")
async def revoke_user_sessions(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """强制用户所有会话下线"""
    # 不允许强制自己下线
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能强制自己下线")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    stmt = update(UserSession).where(
        UserSession.user_id == user_id,
        UserSession.is_revoked == False
    ).values(is_revoked=True)
    await db.execute(stmt)
    
    client_ip = get_client_ip_from_request(request)
    # 记录审计日志
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="强制下线",
        resource="用户",
        detail=f"强制用户 {user.username} 所有会话下线",
        ip_address=client_ip,
        success="true"
    )
    await db.execute(stmt)
    
    await db.commit()
    
    return {"message": "已强制用户所有会话下线"}

@router.get("/roles/", response_model=list[RoleResponse])
async def get_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取角色列表"""
    stmt = select(Role)
    result = await db.execute(stmt)
    roles = result.scalars().all()
    
    role_responses = []
    for role in roles:
        # 获取角色的权限
        perm_stmt = select(Permission).join(
            RolePermission, RolePermission.permission_id == Permission.id
        ).where(RolePermission.role_id == role.id)
        perm_result = await db.execute(perm_stmt)
        permissions = perm_result.scalars().all()
        
        role_responses.append({
            "id": role.id,
            "name": role.name,
            "display_name": role.display_name or role.name,
            "description": role.description,
            "is_builtin": role.is_builtin,
            "permissions": [f"{p.module}:{p.action}" for p in permissions],
            "created_at": role.created_at,
            "updated_at": role.updated_at
        })
    
    return role_responses

@router.post("/roles/", response_model=RoleResponse)
async def create_role(
    role_create: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """创建角色"""
    # 检查角色名是否已存在
    stmt = select(Role).where(Role.name == role_create.name)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="角色标识已存在")
    
    role = Role(
        name=role_create.name,
        display_name=role_create.display_name,
        description=role_create.description,
        is_builtin=role_create.is_builtin
    )
    db.add(role)
    await db.flush()
    
    # 分配权限
    for perm_str in role_create.permissions:
        module, action = perm_str.split(":")
        stmt = select(Permission).where(
            Permission.module == module,
            Permission.action == action
        )
        result = await db.execute(stmt)
        permission = result.scalars().first()
        if permission:
            rp = RolePermission(role_id=role.id, permission_id=permission.id)
            db.add(rp)
    
    await db.commit()
    await db.refresh(role)
    
    # 获取角色权限列表
    perm_stmt = select(Permission).join(
        RolePermission, RolePermission.permission_id == Permission.id
    ).where(RolePermission.role_id == role.id)
    perm_result = await db.execute(perm_stmt)
    permissions = perm_result.scalars().all()
    
    return {
        "id": role.id,
        "name": role.name,
        "display_name": role.display_name or role.name,
        "description": role.description,
        "is_builtin": role.is_builtin,
        "permissions": [f"{p.module}:{p.action}" for p in permissions],
        "created_at": role.created_at,
        "updated_at": role.updated_at
    }

@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    role_update: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """更新角色信息"""
    stmt = select(Role).where(Role.id == role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    if "display_name" in role_update:
        role.display_name = role_update["display_name"]
    if "description" in role_update:
        role.description = role_update["description"]
    
    if "permissions" in role_update and not role.is_builtin:
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        
        for perm_str in role_update["permissions"]:
            if ":" in perm_str:
                module, action = perm_str.split(":")
                perm_stmt = select(Permission).where(
                    Permission.module == module,
                    Permission.action == action
                )
                perm_result = await db.execute(perm_stmt)
                permission = perm_result.scalar_one_or_none()
                
                if permission:
                    await db.execute(insert(RolePermission).values(
                        role_id=role_id,
                        permission_id=permission.id
                    ))
    
    await db.commit()
    await db.refresh(role)
    
    perm_stmt = select(Permission).join(
        RolePermission, RolePermission.permission_id == Permission.id
    ).where(RolePermission.role_id == role.id)
    perm_result = await db.execute(perm_stmt)
    permissions = perm_result.scalars().all()
    
    return {
        "id": role.id,
        "name": role.name,
        "display_name": role.display_name or role.name,
        "description": role.description,
        "is_builtin": role.is_builtin,
        "permissions": [f"{p.module}:{p.action}" for p in permissions],
        "created_at": role.created_at,
        "updated_at": role.updated_at
    }

@router.get("/permissions/", response_model=list[PermissionResponse])
async def get_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取所有权限定义列表"""
    stmt = select(Permission)
    result = await db.execute(stmt)
    permissions = result.scalars().all()
    
    return [{
        "id": p.id,
        "module": p.module,
        "action": p.action,
        "display_name": p.display_name,
        "description": p.description
    } for p in permissions]
