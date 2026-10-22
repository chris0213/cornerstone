"""SSO单点登录服务"""
import httpx
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
import uuid

from ..config import settings
from ..models import User, Role, SystemConfig
from ..schemas.user import UserResponse
from ..utils.security import create_access_token, create_refresh_token, generate_jti, get_password_hash
from ..utils.crypto import decrypt_password
from ..services.permission_service import get_user_permissions


class SSOException(Exception):
    """SSO相关异常"""
    pass


# 与 api/system.py 保持一致：带 enc: 前缀为密文，否则为存量明文
SECRET_ENC_PREFIX = "enc:"


def _decrypt_secret(stored: Optional[str]) -> Optional[str]:
    """解密库中存储的 client_secret（兼容迁移前的明文）。"""
    if not stored:
        return stored
    if stored.startswith(SECRET_ENC_PREFIX):
        return decrypt_password(stored[len(SECRET_ENC_PREFIX):]) or None
    return stored


class SSOConfig:
    """SSO配置"""
    def __init__(self):
        self.enabled = False
        self.client_id = None
        self.client_secret = None
        self.authorize_url = None
        self.token_url = None
        self.userinfo_url = None
        self.redirect_url = None
        self.login_methods = "local,oauth2,saml"
    
    @classmethod
    async def load_from_db(cls, db) -> 'SSOConfig':
        """从数据库加载配置"""
        from sqlalchemy import select
        
        config = cls()
        
        # 先尝试从数据库加载
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "sso_config")
        )
        db_config = result.scalar_one_or_none()
        
        if db_config and db_config.value:
            try:
                config_data = json.loads(db_config.value)
                config.enabled = config_data.get('enabled', False)
                config.client_id = config_data.get('client_id')
                config.client_secret = _decrypt_secret(config_data.get('client_secret'))
                config.authorize_url = config_data.get('authorize_url')
                config.token_url = config_data.get('token_url')
                config.userinfo_url = config_data.get('userinfo_url')
                config.redirect_url = config_data.get('redirect_url')
                config.login_methods = config_data.get('login_methods', 'local,oauth2,saml')
                return config
            except Exception:
                pass
        
        # 如果数据库没有配置，使用环境变量配置
        config.enabled = settings.sso.enabled
        config.client_id = settings.sso.client_id
        config.client_secret = settings.sso.client_secret
        config.authorize_url = settings.sso.authorize_url
        config.token_url = settings.sso.token_url
        config.userinfo_url = settings.sso.userinfo_url
        config.redirect_url = settings.sso.redirect_url
        config.login_methods = settings.sso.login_methods
        
        return config


class SSOService:
    """SSO服务"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30)
    
    async def get_oauth2_authorize_url(self, db, state: str = None) -> str:
        """获取OAuth2授权URL"""
        config = await SSOConfig.load_from_db(db)
        
        if not config.enabled or not config.client_id:
            raise SSOException("SSO未启用或未配置")
        
        state = state or str(uuid.uuid4())
        params = {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": config.redirect_url,
            "scope": "openid email profile",
            "state": state
        }
        
        url = config.authorize_url
        query_string = httpx.QueryParams(params).decode()
        return f"{url}?{query_string}", state
    
    async def exchange_code_for_token(self, db, code: str) -> Dict[str, Any]:
        """使用授权码交换token"""
        config = await SSOConfig.load_from_db(db)
        
        if not config.enabled:
            raise SSOException("SSO未启用")
        
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_url,
            "client_id": config.client_id,
            "client_secret": config.client_secret
        }
        
        response = await self.http_client.post(
            config.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code != 200:
            raise SSOException(f"Token交换失败: {response.text}")
        
        return response.json()
    
    async def get_userinfo(self, db, access_token: str) -> Dict[str, Any]:
        """获取用户信息"""
        config = await SSOConfig.load_from_db(db)
        
        headers = {"Authorization": f"Bearer {access_token}"}
        response = await self.http_client.get(
            config.userinfo_url,
            headers=headers
        )
        
        if response.status_code != 200:
            raise SSOException(f"获取用户信息失败: {response.text}")
        
        return response.json()
    
    async def create_or_update_user(self, db, userinfo: Dict[str, Any]) -> User:
        """创建或更新用户"""
        # 从userinfo中提取用户信息
        email = userinfo.get("email")
        username = userinfo.get("preferred_username") or userinfo.get("username") or email
        display_name = userinfo.get("name") or userinfo.get("display_name") or username
        
        if not username:
            raise SSOException("无法获取用户名")
        
        # email 为非空约束字段，IdP 未返回时用占位域兜底
        if not email:
            email = f"{username}@sso.placeholder"
        
        # 查询现有用户
        from sqlalchemy import select
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            # 更新现有用户信息
            from sqlalchemy import update
            stmt = update(User).where(User.id == user.id).values(
                email=email,
                display_name=display_name,
                is_active=True,
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
            )
            await db.execute(stmt)
            await db.commit()
            
            # 重新查询获取更新后的用户
            stmt = select(User).where(User.id == user.id)
            result = await db.execute(stmt)
            user = result.scalar_one()
        else:
            # 创建新用户：默认角色使用内置 viewer（勿创建孤立角色）
            stmt = select(Role).where(Role.name == "viewer")
            result = await db.execute(stmt)
            role = result.scalar_one_or_none()
            
            if not role:
                raise SSOException("系统内置角色 viewer 不存在，请重新初始化系统")
            
            # 创建用户（密码设置为随机值，SSO用户不需要密码登录）
            random_password = str(uuid.uuid4())
            user = User(
                username=username,
                email=email,
                display_name=display_name,
                hashed_password=get_password_hash(random_password),
                role_id=role.id,
                is_active=True,
                is_sso_user=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        return user
    
    async def generate_login_response(self, db, user: User):
        """生成登录响应"""
        # 获取用户角色和权限
        from sqlalchemy import select
        stmt = select(Role).where(Role.id == user.role_id)
        result = await db.execute(stmt)
        role = result.scalar_one_or_none()
        role_name = role.name if role else ""
        
        permissions = await get_user_permissions(db, user.id)
        
        # 生成JTI
        jti = generate_jti()
        
        # 创建JWT
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            data={
                "sub": user.username,
                "user_id": user.id,
                "role": role_name,
                "permissions": permissions,
                "jti": jti,
                "sso": True
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
        
        # 创建用户会话记录
        from ..models import UserSession
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session = UserSession(
            user_id=user.id,
            jti=jti,
            ip_address=None,
            user_agent="SSO",
            expires_at=now + timedelta(days=7)
        )
        db.add(session)

        # 更新用户最后登录时间
        from sqlalchemy import update
        stmt = update(User).where(User.id == user.id).values(
            last_login_at=now
        )
        await db.execute(stmt)
        
        # 记录审计日志
        from ..models import AuditLog
        from sqlalchemy import insert
        stmt = insert(AuditLog).values(
            user=user.username,
            action="用户登录",
            resource="系统",
            detail="通过SSO登录成功",
            success="true"
        )
        await db.execute(stmt)
        
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
                "is_sso_user": user.is_sso_user
            }
        }
    
    async def oauth2_login(self, db, code: str):
        """OAuth2登录流程"""
        # 1. 交换授权码获取token
        token_data = await self.exchange_code_for_token(db, code)
        access_token = token_data.get("access_token")
        
        if not access_token:
            raise SSOException("未获取到access token")
        
        # 2. 获取用户信息
        userinfo = await self.get_userinfo(db, access_token)
        
        # 3. 创建或更新用户
        user = await self.create_or_update_user(db, userinfo)
        
        # 4. 生成登录响应
        return await self.generate_login_response(db, user)
    
    async def validate_saml_response(self, saml_response: str) -> Dict[str, Any]:
        """验证SAML响应"""
        # SAML实现需要额外的库支持（如pysaml2）
        # 这里提供基础框架，实际实现需要根据IDP配置调整
        raise NotImplementedError("SAML功能尚未实现")
    
    async def saml_login(self, db, saml_response: str):
        """SAML登录流程"""
        # 验证SAML响应
        userinfo = await self.validate_saml_response(saml_response)
        
        # 创建或更新用户
        user = await self.create_or_update_user(db, userinfo)
        
        # 生成登录响应
        return await self.generate_login_response(db, user)


# 创建全局SSO服务实例
sso_service = SSOService()