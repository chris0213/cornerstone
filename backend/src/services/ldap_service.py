"""LDAP认证服务模块"""
import json
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from ldap3 import Server, Connection, ALL, NTLM, Tls, SIMPLE, SUBTREE
from ldap3.core.exceptions import LDAPException, LDAPBindError

from ..config import settings
from ..models import User, Role, SystemConfig
from ..utils.security import create_access_token, create_refresh_token, generate_jti, get_password_hash
from ..utils.crypto import decrypt_password
from ..services.permission_service import get_user_permissions


class LDAPException(Exception):
    """LDAP相关异常"""
    pass


# 与 api/system.py 保持一致：带 enc: 前缀为密文，否则为存量明文
SECRET_ENC_PREFIX = "enc:"


def _decrypt_secret(stored: Optional[str]) -> str:
    """解密库中存储的 bind_password（兼容迁移前的明文）。"""
    if not stored:
        return ""
    if stored.startswith(SECRET_ENC_PREFIX):
        return decrypt_password(stored[len(SECRET_ENC_PREFIX):])
    return stored


class LDAPConfig:
    """LDAP配置"""
    
    def __init__(self):
        self.enabled = False
        self.server = ""
        self.port = 389
        self.use_ssl = False
        self.use_starttls = False
        self.verify_cert = True
        self.bind_dn = ""
        self.bind_password = ""
        self.base_dn = ""
        self.user_filter = "(objectClass=person)"
        self.username_attr = "sAMAccountName"
        self.display_attr = "displayName"
        self.email_attr = "mail"
        self.phone_attr = "mobile"
        self.department_attr = "department"
        self.group_attr = "memberOf"
        self.default_role = "viewer"
    
    @classmethod
    async def load_from_db(cls, db) -> 'LDAPConfig':
        """从数据库加载配置"""
        from sqlalchemy import select
        
        config = cls()
        
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "ldap_config")
        )
        db_config = result.scalar_one_or_none()
        
        if db_config and db_config.value:
            try:
                config_data = json.loads(db_config.value)
                config.enabled = config_data.get('enabled', False)
                config.server = config_data.get('server', '')
                config.port = config_data.get('port', 389)
                config.use_ssl = config_data.get('use_ssl', False)
                config.use_starttls = config_data.get('use_starttls', False)
                config.verify_cert = config_data.get('verify_cert', True)
                config.bind_dn = config_data.get('bind_dn', '')
                config.bind_password = _decrypt_secret(config_data.get('bind_password', ''))
                config.base_dn = config_data.get('base_dn', '')
                config.user_filter = config_data.get('user_filter', '(objectClass=person)')
                config.username_attr = config_data.get('username_attr', 'sAMAccountName')
                config.display_attr = config_data.get('display_attr', 'displayName')
                config.email_attr = config_data.get('email_attr', 'mail')
                config.phone_attr = config_data.get('phone_attr', 'mobile')
                config.department_attr = config_data.get('department_attr', 'department')
                config.group_attr = config_data.get('group_attr', 'memberOf')
                config.default_role = config_data.get('default_role', 'viewer')
                return config
            except Exception:
                pass
        
        return config
    
    def to_dict(self, include_password: bool = False) -> Dict[str, Any]:
        """转换为字典（默认不回显 bind_password，仅返回是否已设置）"""
        data = {
            'enabled': self.enabled,
            'server': self.server,
            'port': self.port,
            'use_ssl': self.use_ssl,
            'use_starttls': self.use_starttls,
            'verify_cert': self.verify_cert,
            'bind_dn': self.bind_dn,
            'has_bind_password': bool(self.bind_password),
            'base_dn': self.base_dn,
            'user_filter': self.user_filter,
            'username_attr': self.username_attr,
            'display_attr': self.display_attr,
            'email_attr': self.email_attr,
            'phone_attr': self.phone_attr,
            'department_attr': self.department_attr,
            'group_attr': self.group_attr,
            'default_role': self.default_role
        }
        if include_password:
            data['bind_password'] = self.bind_password
        return data


class LDAPConnectionManager:
    """LDAP连接管理器"""
    
    def __init__(self, config: LDAPConfig):
        self.config = config
        self.connection = None
    
    def _create_server(self) -> Server:
        """创建LDAP服务器对象"""
        use_ssl = self.config.use_ssl
        
        if self.config.use_starttls and not self.config.use_ssl:
            tls_config = Tls(validate=2 if self.config.verify_cert else 0)
            server = Server(
                self.config.server,
                port=self.config.port,
                use_ssl=False,
                tls=tls_config,
                get_info=ALL
            )
        else:
            server = Server(
                self.config.server,
                port=self.config.port,
                use_ssl=use_ssl,
                get_info=ALL
            )
        
        return server
    
    def connect(self) -> bool:
        """建立LDAP连接"""
        try:
            server = self._create_server()
            
            # 使用管理员账号绑定
            if self.config.bind_dn and self.config.bind_password:
                self.connection = Connection(
                    server,
                    user=self.config.bind_dn,
                    password=self.config.bind_password,
                    authentication=SIMPLE,
                    auto_bind=True
                )
            else:
                # 匿名绑定（如果允许）
                self.connection = Connection(
                    server,
                    auto_bind=True
                )
            
            # 如果启用StartTLS，升级连接
            if self.config.use_starttls and not self.config.use_ssl:
                self.connection.start_tls()
            
            return True
        except LDAPException as e:
            raise LDAPException(f"LDAP连接失败: {str(e)}")
    
    def verify_connection(self) -> bool:
        """验证连接是否可用"""
        if not self.connection:
            return False
        return self.connection.bound
    
    def disconnect(self):
        """关闭连接"""
        if self.connection:
            try:
                self.connection.unbind()
            except:
                pass
            self.connection = None
    
    def search_user(self, username: str) -> Optional[Dict[str, Any]]:
        """搜索用户"""
        if not self.connection or not self.connection.bound:
            raise LDAPException("LDAP连接未建立")
        
        search_filter = f"(&{self.config.user_filter}({self.config.username_attr}={username}))"
        
        try:
            # 搜索用户
            self.connection.search(
                search_base=self.config.base_dn,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=[
                    self.config.username_attr,
                    self.config.display_attr,
                    self.config.email_attr,
                    self.config.phone_attr,
                    self.config.department_attr,
                    self.config.group_attr
                ]
            )
            
            if len(self.connection.entries) == 0:
                return None
            elif len(self.connection.entries) > 1:
                raise LDAPException(f"找到多个匹配的用户: {username}")
            
            entry = self.connection.entries[0]
            return {
                'dn': entry.entry_dn,
                'username': str(entry[self.config.username_attr].value) if entry[self.config.username_attr].value else username,
                'display_name': str(entry[self.config.display_attr].value) if entry[self.config.display_attr].value else username,
                'email': str(entry[self.config.email_attr].value) if entry[self.config.email_attr].value else '',
                'phone': str(entry[self.config.phone_attr].value) if entry[self.config.phone_attr].value else '',
                'department': str(entry[self.config.department_attr].value) if entry[self.config.department_attr].value else '',
                'groups': [str(g) for g in entry[self.config.group_attr].values] if hasattr(entry, self.config.group_attr) and entry[self.config.group_attr].values else []
            }
        except LDAPException as e:
            raise LDAPException(f"搜索用户失败: {str(e)}")
    
    def authenticate_user(self, user_dn: str, password: str) -> bool:
        """验证用户凭据"""
        server = self._create_server()
        
        try:
            # 使用用户自己的凭据绑定
            conn = Connection(
                server,
                user=user_dn,
                password=password,
                authentication=SIMPLE,
                auto_bind=True
            )
            
            if self.config.use_starttls and not self.config.use_ssl:
                conn.start_tls()
            
            success = conn.bound
            conn.unbind()
            return success
        except LDAPBindError:
            return False
        except LDAPException as e:
            raise LDAPException(f"用户认证失败: {str(e)}")


class LDAPAuthService:
    """LDAP认证服务"""
    
    async def get_config(self, db) -> LDAPConfig:
        """获取LDAP配置"""
        return await LDAPConfig.load_from_db(db)
    
    async def test_connection(self, config: LDAPConfig) -> bool:
        """测试LDAP连接"""
        manager = LDAPConnectionManager(config)
        try:
            success = manager.connect()
            manager.disconnect()
            return success
        except Exception:
            return False
    
    async def authenticate(self, db, username: str, password: str) -> Dict[str, Any]:
        """验证用户凭据并获取用户信息"""
        config = await LDAPConfig.load_from_db(db)
        
        if not config.enabled:
            raise LDAPException("LDAP认证未启用")
        
        if not config.server or not config.base_dn:
            raise LDAPException("LDAP配置不完整")
        
        manager = LDAPConnectionManager(config)
        
        try:
            # 1. 使用管理员账号连接
            manager.connect()
            
            # 2. 搜索用户
            user_info = manager.search_user(username)
            if not user_info:
                raise LDAPException("用户名或密码错误")
            
            # 3. 使用用户凭据绑定验证
            if not manager.authenticate_user(user_info['dn'], password):
                raise LDAPException("用户名或密码错误")
            
            return user_info
        finally:
            manager.disconnect()
    
    async def create_or_update_user(self, db, ldap_user: Dict[str, Any]) -> User:
        """创建或更新本地用户"""
        config = await LDAPConfig.load_from_db(db)
        
        from sqlalchemy import select, update
        
        # 查询现有用户（通过LDAP用户名或DN）
        stmt = select(User).where(
            (User.username == ldap_user['username']) |
            (User.ldap_dn == ldap_user['dn'])
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            # 更新现有用户信息
            stmt = update(User).where(User.id == user.id).values(
                display_name=ldap_user['display_name'],
                email=ldap_user['email'] or f"{ldap_user['username']}@example.com",
                ldap_dn=ldap_user['dn'],
                ldap_username=ldap_user['username'],
                department=ldap_user['department'],
                mobile=ldap_user['phone'],
                is_ldap_user=True,
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
            # 创建新用户
            # 获取默认角色
            stmt = select(Role).where(Role.name == config.default_role)
            result = await db.execute(stmt)
            role = result.scalar_one_or_none()
            
            if not role:
                # 如果没有默认角色，获取第一个可用角色或创建
                stmt = select(Role).limit(1)
                result = await db.execute(stmt)
                role = result.scalar_one_or_none()
                
                if not role:
                    role = Role(
                        name=config.default_role,
                        display_name="默认角色",
                        description="LDAP用户默认角色",
                        is_builtin=False
                    )
                    db.add(role)
                    await db.commit()
                    await db.refresh(role)
            
            # 创建用户（密码设置为随机值，LDAP用户不需要密码登录）
            random_password = str(uuid.uuid4())
            user = User(
                username=ldap_user['username'],
                display_name=ldap_user['display_name'],
                email=ldap_user['email'] or f"{ldap_user['username']}@example.com",
                hashed_password=get_password_hash(random_password),
                role_id=role.id,
                is_active=True,
                is_superuser=False,
                is_ldap_user=True,
                ldap_dn=ldap_user['dn'],
                ldap_username=ldap_user['username'],
                department=ldap_user['department'],
                mobile=ldap_user['phone']
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        return user
    
    async def generate_login_response(self, db, user: User, client_ip: str = None, user_agent: str = ""):
        """生成登录响应"""
        from sqlalchemy import select, insert, update
        
        # 获取用户角色和权限
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
                "ldap": True
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
            ip_address=client_ip,
            user_agent=user_agent,
            expires_at=now + timedelta(days=7)
        )
        db.add(session)
        
        # 更新用户最后登录时间
        stmt = update(User).where(User.id == user.id).values(
            last_login_at=now,
            last_login_ip=client_ip
        )
        await db.execute(stmt)
        
        # 记录审计日志
        from ..models import AuditLog
        stmt = insert(AuditLog).values(
            user=user.username,
            action="用户登录",
            resource="系统",
            detail="通过LDAP登录成功",
            ip_address=client_ip,
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
                "is_sso_user": user.is_sso_user,
                "is_ldap_user": user.is_ldap_user
            }
        }
    
    async def login(self, db, username: str, password: str, client_ip: str = None, user_agent: str = ""):
        """LDAP登录流程"""
        # 1. 验证LDAP凭据
        ldap_user = await self.authenticate(db, username, password)
        
        # 2. 创建或更新本地用户
        user = await self.create_or_update_user(db, ldap_user)
        
        # 3. 生成登录响应
        return await self.generate_login_response(db, user, client_ip, user_agent)


# 创建全局LDAP服务实例
ldap_service = LDAPAuthService()
