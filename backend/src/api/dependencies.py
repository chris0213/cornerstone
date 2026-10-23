from dataclasses import dataclass

from fastapi import Depends, HTTPException, Query, status, WebSocket, WebSocketException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..database import get_db
from ..models import User, UserSession
from ..utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


@dataclass(frozen=True)
class PageParams:
    """统一分页参数"""
    skip: int
    limit: int


def pagination(default_limit: int = 100, max_limit: int = 1000):
    """分页查询参数依赖，生成 skip/limit 查询参数并校验取值范围。

    用法：`page: PageParams = Depends(pagination())`，
    查询时使用 `query.offset(page.skip).limit(page.limit)`。
    需要非默认 limit 的接口传 `pagination(default_limit=50)`。
    """
    def _pagination(
        skip: int = Query(0, ge=0, description="跳过条数"),
        limit: int = Query(default_limit, ge=1, le=max_limit, description="返回条数"),
    ) -> PageParams:
        return PageParams(skip=skip, limit=limit)

    return _pagination

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    user_id: int = payload.get("user_id")
    jti: str = payload.get("jti")
    
    if username is None:
        raise credentials_exception
    
    # 检查会话是否已被撤销
    stmt = select(UserSession).where(
        UserSession.jti == jti,
        UserSession.is_revoked == False
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 使用 select 查询用户，预加载role关系避免懒加载
    stmt = select(User).options(joinedload(User.role)).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="账号已被禁用")
    return current_user

async def get_current_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="没有足够的权限"
        )
    return current_user

async def require_super_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """要求超级管理员权限"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要超级管理员权限"
        )
    return current_user

def require_permission(permission: str):
    """权限依赖装饰器"""
    async def permission_check(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
    ) -> User:
        # 超级用户跳过权限检查
        if current_user.is_superuser:
            return current_user

        from ..services.permission_service import has_permission as check_permission

        # 解析权限字符串 (格式: module:action)
        if ':' in permission:
            module, action = permission.split(':', 1)
        else:
            module = permission
            action = 'read'

        if not await check_permission(db, current_user.id, module, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限: {permission}"
            )
        return current_user

    return permission_check

def require_permissions(permissions: List[str]):
    """多权限依赖装饰器（满足任一即可）"""
    async def permissions_check(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db)
    ) -> User:
        # 超级用户跳过权限检查
        if current_user.is_superuser:
            return current_user
        
        from ..services.permission_service import has_permission as check_permission
        
        for permission in permissions:
            if ':' in permission:
                module, action = permission.split(':', 1)
            else:
                module = permission
                action = 'read'
            
            if await check_permission(db, current_user.id, module, action):
                return current_user
        
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"缺少必要权限，需要以下任一权限: {', '.join(permissions)}"
        )
    return permissions_check

async def get_ws_user(
    websocket: WebSocket,
    db: AsyncSession
) -> User:
    """WebSocket 鉴权：从 query 参数提取 token 并验证用户

    同时执行 IP 白名单检查（HTTP middleware 不覆盖 WebSocket，
    故在统一的 WS 鉴权入口拦截；仅用直连 IP，不采信代理头）。
    """
    from .utils.ip_whitelist import check_ws_ip_allowed
    if not await check_ws_ip_allowed(websocket):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="IP 不在白名单中"
        )

    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="缺少认证 token")
    
    payload = decode_access_token(token)
    if payload is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="无效的认证 token")
    
    username = payload.get("sub")
    user_id = payload.get("user_id")
    jti = payload.get("jti")
    
    if username is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="token 无效")
    
    stmt = select(UserSession).where(
        UserSession.jti == jti,
        UserSession.is_revoked == False
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="会话已被撤销")
    
    stmt = select(User).options(joinedload(User.role)).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user is None or not user.is_active:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="用户不存在或已禁用")
    
    return user
