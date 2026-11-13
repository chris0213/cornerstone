from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import List, Optional

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    display_name: Optional[str] = None
    role_id: Optional[int] = None
    is_active: bool = True
    # 仅平台超管可指定；普通调用者会被强制写为自身租户
    tenant_id: Optional[int] = None

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    # 仅平台超管可变更用户租户归属
    tenant_id: Optional[int] = None

class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    display_name: Optional[str]
    role: Optional[str]
    role_display_name: Optional[str]
    permissions: List[str] = []
    is_active: bool
    is_superuser: bool
    is_sso_user: bool
    tenant_id: Optional[int] = None
    last_login_at: Optional[datetime]
    last_login_ip: Optional[str]
    avatar: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 7200
    refresh_token: Optional[str] = None
    user: Optional[dict] = None

class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: Optional[str] = None
    permissions: List[str] = []
    jti: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class ResetPasswordResponse(BaseModel):
    message: str
    new_password: str

class UserSessionResponse(BaseModel):
    id: int
    user_id: int
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    expires_at: datetime
    is_revoked: bool
    
    class Config:
        from_attributes = True
