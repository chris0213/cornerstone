from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
from typing import Optional

class SSOSettings(BaseSettings):
    """SSO配置"""
    # SSO启用开关
    enabled: bool = False
    
    # OAuth2通用配置
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    userinfo_url: Optional[str] = None
    redirect_url: Optional[str] = None
    
    # SAML配置
    saml_enabled: bool = False
    idp_metadata_url: Optional[str] = None
    sp_entity_id: Optional[str] = None
    
    # 登录方式优先级 (local, oauth2, saml)
    login_methods: str = "local,oauth2,saml"

class NotificationSettings(BaseSettings):
    """通知渠道配置"""
    # 钉钉机器人Webhook地址
    dingtalk_webhook_url: Optional[str] = Field(None, alias="DINGTALK_WEBHOOK_URL")
    # 企业微信机器人Webhook地址
    wechat_webhook_url: Optional[str] = Field(None, alias="WECHAT_WEBHOOK_URL")
    # 飞书机器人Webhook地址
    feishu_webhook_url: Optional[str] = Field(None, alias="FEISHU_WEBHOOK_URL")
    
    # 邮件服务器配置
    smtp_host: Optional[str] = Field(None, alias="SMTP_HOST")
    smtp_port: Optional[int] = Field(587, alias="SMTP_PORT")
    smtp_username: Optional[str] = Field(None, alias="SMTP_USERNAME")
    smtp_password: Optional[str] = Field(None, alias="SMTP_PASSWORD")
    smtp_from_email: Optional[str] = Field(None, alias="SMTP_FROM_EMAIL")
    
    model_config = SettingsConfigDict(populate_by_name=True)

class Settings(BaseSettings):
    # 数据库配置
    database_url: str
    database_url_sync: str
    
    # Redis配置
    redis_url: str = "redis://localhost:6379/0"
    
    # JWT配置
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8小时
    
    # 凭证加密配置
    credential_secret_key: str | None = None

    # 凭证测试连接限流：同一凭证 N 秒内只允许 1 次（0 = 不限流）
    credential_test_rate_limit_seconds: int = 10
    # 凭证测试连接是否放行私网段目标（False = 仅允许设备表内已登记 IP）
    credential_test_allow_private: bool = True
    
    # 应用配置
    app_name: str = "Cornerstone API"
    app_version: str = "1.0.0"
    debug: bool = False

    # CORS 配置（多个来源用逗号分隔）
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    
    # 备份配置
    backup_dir: str = "/opt/cornerstone/backups"
    
    # SSO配置
    sso: SSOSettings = SSOSettings()
    
    # 通知渠道配置
    notification: NotificationSettings = NotificationSettings()
    
    model_config = SettingsConfigDict(env_file=Path(__file__).parent.parent / ".env", env_nested_delimiter="__", extra="allow")

settings = Settings()
