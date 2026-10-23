from pydantic import BaseModel
from typing import Optional

class SettingResponse(BaseModel):
    key: str
    value: str

    class Config:
        from_attributes = True

# 品牌设置的请求/响应模型已内联在 src/api/settings.py（名称锁定由后端强制，请求模型不含名称字段）

class NotificationSettingsRequest(BaseModel):
    """PUT 请求：密钥字段传 None/空串 = 留空不修改（保留库中旧值）"""
    dingtalk_webhook_url: Optional[str] = None
    wechat_webhook_url: Optional[str] = None
    feishu_webhook_url: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 25
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: Optional[str] = None
    smtp_security: Optional[str] = "starttls"
    channel_enabled: Optional[dict] = None

class NotificationSettingsResponse(BaseModel):
    """GET 响应：密钥字段只回 has_xxx + 尾 8 字符，不回原文"""
    has_dingtalk_webhook_url: bool = False
    has_wechat_webhook_url: bool = False
    has_feishu_webhook_url: bool = False
    has_smtp_password: bool = False
    dingtalk_webhook_url_tail: str = ""
    wechat_webhook_url_tail: str = ""
    feishu_webhook_url_tail: str = ""
    smtp_password_tail: str = ""
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_from_email: Optional[str] = None
    smtp_security: str = "starttls"
    channel_enabled: dict = {}

class TestNotificationResponse(BaseModel):
    success: bool
    message: str
    channel: str
    status: str  # sent / failed
    error: Optional[str] = None
