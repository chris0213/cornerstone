from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from ..database import Base, UTCDateTime

class Role(Base):
    """角色"""
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)           # super_admin / engineer / viewer
    display_name = Column(String(50), nullable=False)                 # 超级管理员 / IT运维工程师 / 只读查看者
    description = Column(String(255))
    is_builtin = Column(Boolean, default=False)                      # True=内置角色不可删除
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
    
    users = relationship("User", back_populates="role")
    permissions = relationship("RolePermission", back_populates="role")

class Permission(Base):
    """权限定义"""
    __tablename__ = "permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    module = Column(String(50), nullable=False)                      # sites / circuits / ipam / devices / backups / topology / alerts / system / logs
    action = Column(String(50), nullable=False)                      # read / write / delete / export / backup_exec / scan_exec
    display_name = Column(String(100))                               # 如「站点管理-新增编辑」
    description = Column(String(255))
    
    roles = relationship("RolePermission", back_populates="permission")

class RolePermission(Base):
    """角色-权限关联"""
    __tablename__ = "role_permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id"))
    permission_id = Column(Integer, ForeignKey("permissions.id"))
    
    role = relationship("Role", back_populates="permissions")
    permission = relationship("Permission", back_populates="roles")

class User(Base):
    """用户"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)       # 唯一，登录用
    display_name = Column(String(100))                               # 显示名，如「张三」
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)            # bcrypt哈希
    role_id = Column(Integer, ForeignKey("roles.id"))                # 关联 roles.id
    is_active = Column(Boolean, default=True)                        # 是否启用
    is_superuser = Column(Boolean, default=False)                    # 超级管理员标记
    is_sso_user = Column(Boolean, default=False)                     # 是否SSO用户
    is_ldap_user = Column(Boolean, default=False)                    # 是否LDAP用户
    ldap_dn = Column(String(500))                                    # LDAP DN
    ldap_username = Column(String(100))                              # LDAP 用户名
    department = Column(String(200))                                  # 部门
    mobile = Column(String(50))                                       # 手机号码
    last_login_at = Column(UTCDateTime)                  # 最后登录时间
    last_login_ip = Column(String(50))                               # 最后登录IP
    avatar = Column(String(255))                                     # 头像URL（可选）
    locale = Column(String(10), default="zh-CN")                      # 语言偏好 zh-CN / en-US
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
    
    role = relationship("Role", back_populates="users")

class UserSession(Base):
    """登录会话记录（用于强制下线）"""
    __tablename__ = "user_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    jti = Column(String(36), unique=True, nullable=False)            # JWT ID，用于失效单个token
    ip_address = Column(String(50))
    user_agent = Column(String(255))
    created_at = Column(UTCDateTime, server_default=func.now())
    expires_at = Column(UTCDateTime)
    is_revoked = Column(Boolean, default=False)                      # True=已强制下线
    
    user = relationship("User")
