from datetime import timedelta, datetime, timezone
from typing import Optional
import logging
import random
import string
import io
from PIL import Image

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from captcha.image import ImageCaptcha
import redis.asyncio as aioredis

from ..utils.ip_whitelist import get_client_ip_from_request, get_cached_whitelist, is_ip_in_networks

from ..database import get_db
from ..models import User, AuditLog, UserSession, Role
from ..schemas import Token, UserResponse, ChangePasswordRequest
from ..utils.security import (
    verify_password, 
    create_access_token, 
    create_refresh_token,
    generate_jti,
    is_account_locked,
    record_login_failure,
    reset_login_failures,
    validate_password,
    get_password_hash
)
from ..config import settings
from ..services.permission_service import get_user_permissions
from ..services.sso_service import sso_service, SSOException
from .dependencies import get_current_active_user

router = APIRouter()

logger = logging.getLogger(__name__)

# Request body models
class CaptchaLoginRequest(BaseModel):
    """验证码登录请求体"""
    username: str
    password: str
    captcha_id: str
    captcha_code: str

# SSO相关路由

async def get_redis():
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
@router.get("/sso/config")
async def get_sso_config():
    """获取SSO配置信息"""
    sso_config = settings.sso
    return {
        "enabled": sso_config.enabled,
        "login_methods": sso_config.login_methods.split(","),
        "has_oauth2": bool(sso_config.client_id and sso_config.authorize_url),
        "has_saml": sso_config.saml_enabled
    }

@router.get("/sso/authorize")
async def sso_authorize(
    db: AsyncSession = Depends(get_db)
):
    """获取SSO授权URL"""
    try:
        authorize_url, state = await sso_service.get_oauth2_authorize_url(db)
        return {"authorize_url": authorize_url, "state": state}
    except SSOException as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/sso/callback")
async def sso_callback(
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """SSO回调处理"""
    try:
        result = await sso_service.oauth2_login(db, code)
        return result
    except SSOException as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/sso/saml/callback")
async def saml_callback(
    saml_response: str,
    db: AsyncSession = Depends(get_db)
):
    """SAML回调处理"""
    try:
        result = await sso_service.saml_login(db, saml_response)
        return result
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="SAML功能尚未实现")
    except SSOException as e:
        raise HTTPException(status_code=400, detail=str(e))

def generate_random_code(length: int = 4):
    """生成随机验证码"""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

async def log_login_attempt(db: AsyncSession, username: str, success: bool, ip_address: str = None):
    """记录登录尝试日志"""
    detail = "登录成功" if success else "登录失败：用户名或密码错误"
    stmt = insert(AuditLog).values(
        user=username,
        action="用户登录",
        resource="系统",
        detail=detail,
        ip_address=ip_address,
        success="true" if success else "false"
    )
    await db.execute(stmt)
    await db.commit()


async def _perform_login(db: AsyncSession, user: User, client_ip: str, user_agent: str) -> dict:
    """公共登录核心逻辑：生成 token、创建 session、记录日志"""
    # IP 白名单前置检查：普通用户不在白名单时拒绝登录并给出明确提示，
    # 避免出现"登录成功但所有请求被 403、刷新即被踢回登录页"的困惑体验。
    # super_admin 放行，保留白名单误配后从页面自救的通道（与 main.py 中间件防自锁设计一致）。
    if client_ip not in ("127.0.0.1", "::1", "localhost") and not user.is_superuser:
        try:
            networks = await get_cached_whitelist(db)
            if networks and not is_ip_in_networks(client_ip, networks):
                await log_login_attempt(db, user.username, False, client_ip)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="您的IP地址不在访问白名单中，请联系管理员添加"
                )
        except HTTPException:
            raise
        except Exception:
            # 检查过程出错默认放行（与中间件 fail-open 语义一致，避免锁死系统）
            logger.error("[IP白名单] 登录前置检查出错，默认放行")

    stmt = select(Role).where(Role.id == user.role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    role_name = role.name if role else ""

    permissions = await get_user_permissions(db, user.id)

    jti = generate_jti()
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": role_name,
            "permissions": permissions,
            "jti": jti
        },
        expires_delta=access_token_expires
    )
    refresh_token = create_refresh_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "jti": jti
        }
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = UserSession(
        user_id=user.id,
        jti=jti,
        ip_address=client_ip,
        user_agent=user_agent,
        expires_at=now + timedelta(days=7)
    )
    db.add(session)

    stmt = update(User).where(User.id == user.id).values(
        last_login_at=now,
        last_login_ip=client_ip
    )
    await db.execute(stmt)

    await log_login_attempt(db, user.username, True, client_ip)
    reset_login_failures(user.username)
    await db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": access_token_expires.seconds,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "email": user.email,
            "role": role_name,
            "role_display_name": role.display_name if role else "",
            "permissions": permissions,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser
        }
    }


@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    client_ip = get_client_ip_from_request(request)
    user_agent = request.headers.get("User-Agent", "")

    if is_account_locked(form_data.username):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="账号已被锁定，请15分钟后重试")

    stmt = select(User).where(User.username == form_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        await log_login_attempt(db, form_data.username, False, client_ip)
        record_login_failure(form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        await log_login_attempt(db, user.username, False, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _perform_login(db, user, client_ip, user_agent)

@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """退出登录，将当前jti标记为revoked"""
    # 从请求头获取token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的认证token"
        )
    
    token = auth_header[7:]
    
    # 查询并撤销会话
    stmt = update(UserSession).where(
        UserSession.user_id == current_user.id,
        UserSession.is_revoked == False
    ).values(is_revoked=True)
    await db.execute(stmt)
    await db.commit()
    
    return {"message": "退出登录成功"}

@router.get("/me", response_model=UserResponse)
async def read_users_me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取当前登录用户信息（通过 get_current_active_user 统一校验 session 撤销）"""
    stmt = select(Role).where(Role.id == current_user.role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()

    permissions = await get_user_permissions(db, current_user.id)

    return {
        "id": current_user.id,
        "username": current_user.username,
        "display_name": current_user.display_name or current_user.username,
        "email": current_user.email,
        "role": role.name if role else "",
        "role_display_name": role.display_name if role else "",
        "permissions": permissions,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "is_sso_user": current_user.is_sso_user,
        "last_login_at": current_user.last_login_at,
        "last_login_ip": current_user.last_login_ip,
        "avatar": current_user.avatar,
        "created_at": current_user.created_at,
        "updated_at": current_user.updated_at
    }

@router.post("/change-password")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """修改自己的密码"""
    # 验证旧密码
    if not verify_password(body.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码不正确"
        )
    
    # 验证新密码强度
    if not validate_password(body.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码至少8位，包含字母和数字"
        )
    
    # 更新密码
    hashed_password = get_password_hash(body.new_password)
    stmt = update(User).where(User.id == current_user.id).values(
        hashed_password=hashed_password,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    await db.execute(stmt)
    
    # 获取客户端 IP
    client_ip = get_client_ip_from_request(request)

    # 记录审计日志
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="修改密码",
        resource="用户",
        detail=f"用户 {current_user.username} 修改了自己的密码",
        ip_address=client_ip,
        success="true"
    )
    await db.execute(stmt)
    
    await db.commit()
    
    return {"message": "密码修改成功"}

@router.post("/refresh")
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """刷新token"""
    # 获取refresh token
    refresh_token = request.headers.get("X-Refresh-Token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少refresh token"
        )
    
    # 解码refresh token
    from jose import jwt as jose_jwt
    try:
        payload = jose_jwt.decode(refresh_token, settings.secret_key, algorithms=[settings.algorithm])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的refresh token"
        )
    
    user_id = payload.get("user_id")
    jti = payload.get("jti")
    if not user_id or not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的refresh token"
        )

    # 校验 session 未被撤销
    stmt = select(UserSession).where(
        UserSession.jti == jti,
        UserSession.is_revoked == False
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token已失效，请重新登录"
        )

    # 查询用户
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用"
        )
    
    # 获取用户角色和权限
    stmt = select(Role).where(Role.id == user.role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    role_name = role.name if role else ""
    
    permissions = await get_user_permissions(db, user.id)
    
    # 生成新的JTI
    jti = generate_jti()
    
    # 创建新的access token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": role_name,
            "permissions": permissions,
            "jti": jti
        }, 
        expires_delta=access_token_expires
    )
    
    # 创建新的refresh token
    new_refresh_token = create_refresh_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "jti": jti
        }
    )

    # Token rotation：撤销旧 session，创建新 session
    stmt = update(UserSession).where(
        UserSession.jti == payload.get("jti"),
        UserSession.is_revoked == False
    ).values(is_revoked=True)
    await db.execute(stmt)

    from datetime import timezone
    client_ip = get_client_ip_from_request(request)
    session_expire = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    new_session = UserSession(
        user_id=user.id,
        jti=jti,
        ip_address=client_ip,
        user_agent=request.headers.get("User-Agent", ""),
        expires_at=session_expire
    )
    db.add(new_session)

    await db.commit()
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": access_token_expires.seconds,
        "refresh_token": new_refresh_token
    }

@router.get("/captcha")
async def get_captcha(redis=Depends(get_redis)):
    """获取图形验证码"""
    captcha_id = generate_jti()
    captcha_code = generate_random_code()
    
    await redis.setex(f"captcha:{captcha_id}", 300, captcha_code.lower())
    
    image = ImageCaptcha(width=200, height=80)
    data = image.generate(captcha_code)
    
    return StreamingResponse(
        io.BytesIO(data.getvalue()),
        media_type="image/png",
        headers={"X-Captcha-ID": captcha_id}
    )
@router.post("/login-with-captcha")
async def login_with_captcha(
    request: Request,
    body: CaptchaLoginRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis)
):
    """带验证码的登录接口"""
    stored_code = await redis.get(f"captcha:{body.captcha_id}")
    if not stored_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期，请刷新")

    if body.captcha_code.lower() != stored_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")

    await redis.delete(f"captcha:{body.captcha_id}")

    client_ip = get_client_ip_from_request(request)
    user_agent = request.headers.get("User-Agent", "")

    if is_account_locked(body.username):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="账号已被锁定，请15分钟后重试")

    stmt = select(User).where(User.username == body.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        await log_login_attempt(db, body.username, False, client_ip)
        record_login_failure(body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        await log_login_attempt(db, user.username, False, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _perform_login(db, user, client_ip, user_agent)
