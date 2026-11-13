from datetime import datetime, timedelta, timezone
import random
import string
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, File, UploadFile, Response
from fastapi.responses import RedirectResponse
from email.utils import format_datetime, parsedate_to_datetime
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.orm import joinedload

from ..database import get_db
from ..models import User, Role, Permission, RolePermission, UserSession, AuditLog
from ..schemas import UserCreate, UserUpdate, UserResponse, ResetPasswordResponse, UserSessionResponse, RoleResponse, RoleCreate, PermissionResponse
from ..utils.security import get_password_hash, validate_password
from ..utils.ip_whitelist import get_client_ip_from_request
from .dependencies import get_current_active_user, require_permission, PageParams, pagination
from .permissions import role_conflict, _audit
from ..services.permission_service import has_permission
from ..services.avatar_service import (
    MAX_AVATAR_BYTES, AvatarValidationError, avatar_etag, avatar_url, process_avatar,
)
from ..utils.timeutil import ensure_utc, utc_now

router = APIRouter()


async def _can(db: AsyncSession, user: User, module: str, action: str) -> bool:
    """超级管理员直接放行，其余按角色权限判断。"""
    return user.is_superuser or await has_permission(db, user.id, module, action)


async def _ensure_role_allowed(db: AsyncSession, operator: User, role_id: int | None) -> None:
    """非超管不得把用户提升为超级管理员角色，避免权限提升。"""
    if role_id is None or operator.is_superuser:
        return
    role = await db.get(Role, role_id)
    if role and role.name == "super_admin":
        raise HTTPException(status_code=403, detail="只有超级管理员可以分配超级管理员角色")


def _ensure_superuser_target(operator: User, target: User) -> None:
    """非超管不得操作超级管理员账号。"""
    if target.is_superuser and not operator.is_superuser:
        raise HTTPException(status_code=403, detail="只有超级管理员可以操作超级管理员账号")

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
        avatar=avatar_url(user),
        created_at=user.created_at,
        updated_at=user.updated_at
    )

@router.get("/", response_model=list[UserResponse], dependencies=[Depends(require_permission("users:read"))])
async def read_users(
    page: PageParams = Depends(pagination()),
    role: str = None,
    is_active: bool = None,
    keyword: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取用户列表（需要 users:read 权限）"""
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
    # 本人可查看自己；查看他人需要 users:read
    if current_user.id != user_id and not await _can(db, current_user, "users", "read"):
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

@router.post("/{user_id}/avatar")
async def upload_user_avatar(
    request: Request,
    user_id: int,
    avatar: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """上传头像：本人或 users:write；服务端缩放到 256x256 后存库。"""
    if current_user.id != user_id and not await _can(db, current_user, "users", "write"):
        raise HTTPException(status_code=403, detail="没有足够的权限")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if current_user.id != user_id:
        _ensure_superuser_target(current_user, user)

    raw = await avatar.read(MAX_AVATAR_BYTES + 1)
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail=f"头像不能超过 {MAX_AVATAR_BYTES // 1024}KB")

    try:
        data, content_type = process_avatar(raw)
    except AvatarValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user.avatar_data = data
    user.avatar_content_type = content_type
    user.avatar_version = (user.avatar_version or 0) + 1
    user.avatar_updated_at = utc_now()
    await _audit(
        db, request, current_user.username, "更新用户头像",
        f"目标用户：{user.username}，版本：{user.avatar_version}，大小：{len(data)} 字节",
    )
    await db.commit()
    await db.refresh(user)
    return {"avatar_url": avatar_url(user), "version": user.avatar_version}


@router.get("/{user_id}/avatar")
async def get_user_avatar(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """读取头像（公开只读，供 <img> 直接加载），支持 ETag/Last-Modified/304。"""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 历史数据只有外部 URL 时直接跳转，保持兼容
    if not user.avatar_data:
        if user.avatar:
            return RedirectResponse(user.avatar)
        raise HTTPException(status_code=404, detail="未设置头像")

    etag = avatar_etag(user)
    last_modified = ensure_utc(user.avatar_updated_at) if user.avatar_updated_at else None
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if last_modified:
        headers["Last-Modified"] = format_datetime(last_modified, usegmt=True)

    inm = request.headers.get("if-none-match")
    if inm:
        tags = [t.strip() for t in inm.split(",")]
        tags = [t[2:] if t.startswith("W/") else t for t in tags]
        if "*" in tags or etag in tags:
            return Response(status_code=304, headers=headers)

    ims = request.headers.get("if-modified-since")
    if ims and last_modified:
        try:
            since = parsedate_to_datetime(ims)
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            if last_modified <= since + timedelta(seconds=1):
                return Response(status_code=304, headers=headers)
        except (TypeError, ValueError, OverflowError):
            pass

    return Response(
        content=user.avatar_data,
        media_type=user.avatar_content_type or "image/webp",
        headers=headers,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("users:write"))])
@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False, dependencies=[Depends(require_permission("users:write"))])
async def create_user(
    request: Request,
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
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

    # 非超管不得创建超级管理员角色的账号
    await _ensure_role_allowed(db, current_user, user.role_id)

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
    # 本人可编辑自己；编辑他人需要 users:write
    if current_user.id != user_id and not await _can(db, current_user, "users", "write"):
        raise HTTPException(status_code=403, detail="没有足够的权限")
    
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if current_user.id != user_id:
        _ensure_superuser_target(current_user, target_user)
        await _ensure_role_allowed(db, current_user, user.role_id)
    
    update_data = user.model_dump(exclude_unset=True)
    
    # 普通用户静默忽略 is_active / role_id（仅超管可改）
    if not current_user.is_superuser:
        update_data.pop("is_active", None)
        update_data.pop("role_id", None)
    
    # 超管也不允许把「最后一个启用超管」改成其他角色
    if "role_id" in update_data and update_data["role_id"] != target_user.role_id and target_user.is_superuser and target_user.is_active:
        count_result = await db.execute(
            select(func.count(User.id)).where(
                User.is_superuser == True,  # noqa: E712
                User.is_active == True  # noqa: E712
            )
        )
        if count_result.scalar_one() <= 1:
            raise HTTPException(status_code=400, detail="系统必须保留至少一个启用状态的超级管理员")
    
    if not update_data:
        return await build_user_response(db, target_user)
    
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

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("users:delete"))])
async def delete_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """删除用户（需要 users:delete 权限）"""
    # 不允许删除自己
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    _ensure_superuser_target(current_user, user)
    
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

@router.patch("/{user_id}/toggle", response_model=UserResponse, dependencies=[Depends(require_permission("users:write"))])
async def toggle_user_status(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """启用/停用用户"""
    # 不允许停用自己
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能停用自己")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    _ensure_superuser_target(current_user, user)
    
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

@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse, dependencies=[Depends(require_permission("users:write"))])
async def reset_password(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """重置用户密码（需要 users:write 权限）"""
    # 不允许重置自己的密码（应使用change-password接口）
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="请使用个人设置中的修改密码功能")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    _ensure_superuser_target(current_user, user)
    
    # 重置密码同样会使当前会话失效，需保护最后一个启用超管
    if user.is_superuser and user.is_active:
        count_result = await db.execute(
            select(func.count(User.id)).where(
                User.is_superuser == True,  # noqa: E712
                User.is_active == True  # noqa: E712
            )
        )
        if count_result.scalar_one() <= 1:
            raise HTTPException(status_code=400, detail="系统必须保留至少一个启用状态的超级管理员")
    
    # 生成随机密码
    new_password = generate_random_password()
    hashed_password = get_password_hash(new_password)
    
    stmt = update(User).where(User.id == user_id).values(
        hashed_password=hashed_password,
        updated_at=utc_now()
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
    current_user: User = Depends(get_current_active_user)
):
    """查看用户登录会话列表：本人或 users:read"""
    if current_user.id != user_id and not await _can(db, current_user, "users", "read"):
        raise HTTPException(status_code=403, detail="没有足够的权限")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    stmt = select(UserSession).where(UserSession.user_id == user_id).order_by(UserSession.created_at.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    
    return sessions

@router.post("/{user_id}/revoke-sessions", dependencies=[Depends(require_permission("users:write"))])
async def revoke_user_sessions(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """强制用户所有会话下线"""
    # 不允许强制自己下线
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能强制自己下线")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    _ensure_superuser_target(current_user, user)
    
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

@router.delete("/{user_id}/sessions/{session_id}", dependencies=[Depends(require_permission("users:write"))])
async def revoke_user_session(
    request: Request,
    user_id: int,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """吊销用户单个会话"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    _ensure_superuser_target(current_user, user)
    
    stmt = select(UserSession).where(
        UserSession.id == session_id,
        UserSession.user_id == user_id
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.is_revoked:
        raise HTTPException(status_code=400, detail="该会话已吊销")
    
    await db.execute(
        update(UserSession).where(UserSession.id == session_id).values(is_revoked=True)
    )
    
    client_ip = get_client_ip_from_request(request)
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="强制下线",
        resource="用户",
        detail=f"吊销用户 {user.username} 的单个会话 (jti={session.jti})",
        ip_address=client_ip,
        success="true"
    )
    await db.execute(stmt)
    
    await db.commit()
    
    return {"message": "会话已吊销"}

@router.get("/roles/", response_model=list[RoleResponse], dependencies=[Depends(require_permission("system:admin"))])
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

@router.post("/roles/", response_model=RoleResponse, dependencies=[Depends(require_permission("system:admin"))])
async def create_role(
    request: Request,
    role_create: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
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
        display_name=role_create.display_name or role_create.name,
        description=role_create.description,
        is_builtin=False  # API 创建的角色一律为非内置
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
    
    await _audit(db, request, current_user.username, "创建角色", f"创建角色 {role.name}")
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

@router.put("/roles/{role_id}", response_model=RoleResponse, dependencies=[Depends(require_permission("system:admin"))])
async def update_role(
    request: Request,
    role_id: int,
    role_update: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """更新角色信息"""
    stmt = select(Role).where(Role.id == role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 内置角色禁止任何修改（display_name / description / permissions）
    if role.is_builtin:
        raise role_conflict(
            "system.roleBuiltin",
            "内置角色不允许修改",
            name=role.name,
        )
    
    changed_fields = []
    if "display_name" in role_update:
        role.display_name = role_update["display_name"]
        changed_fields.append("display_name")
    if "description" in role_update:
        role.description = role_update["description"]
        changed_fields.append("description")
    
    if "permissions" in role_update:
        changed_fields.append(f"permissions({len(role_update['permissions'])}项)")
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
    
    await _audit(db, request, current_user.username, "修改角色",
                 f"修改角色 {role.name}，修改内容: {', '.join(changed_fields) if changed_fields else '无'}")
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

@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("system:admin"))])
async def delete_role(
    request: Request,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """删除角色（内置角色与使用中的角色禁止删除）"""
    stmt = select(Role).where(Role.id == role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    if role.is_builtin:
        raise role_conflict("system.roleBuiltin", "内置角色不允许删除", name=role.name)
    
    user_count_result = await db.execute(
        select(func.count(User.id)).where(User.role_id == role_id)
    )
    user_count = user_count_result.scalar_one()
    if user_count > 0:
        raise role_conflict(
            "system.roleInUse",
            "角色仍有用户使用，不允许删除",
            name=role.name,
            count=user_count,
        )
    
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    await _audit(db, request, current_user.username, "删除角色", f"删除角色 {role.name}")
    await db.execute(delete(Role).where(Role.id == role_id))
    await db.commit()

@router.get("/permissions/", response_model=list[PermissionResponse], dependencies=[Depends(require_permission("system:admin"))])
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
