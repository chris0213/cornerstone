from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
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
    # 凭证测试连接是否放行私网段目标（True = 可测试内网 IP；False = 仅允许设备表内已登记 IP）
    # 生产环境建议默认 False：避免攻击者在"凭证测试连接"里 SSRF 探测内网
    credential_test_allow_private: bool = False
    
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

    @model_validator(mode='after')
    def _validate_critical_secrets(self) -> "Settings":
        """启动时校验关键密钥配置，避免弱密钥/空密钥在生产默默生效。"""
        if not self.secret_key or len(self.secret_key) < 32:
            # FastAPI 会把 Pydantic 校验异常原样抛到启动栈顶，运维一眼就能看到
            raise ValueError(
                "SECRET_KEY 必须设置且至少 32 个字符（HS256 要求 256bit 以上）。"
                f"当前长度: {len(self.secret_key) if self.secret_key else 0}。"
                "请在 .env 或环境变量里生成一个强随机值（例如 openssl rand -hex 32）。"
            )
        # REDIS_URL 带密码才算配置安全：生产 compose 已通过 REDIS_PASSWORD 注入，
        # 但本地直接跑 backend 容易忘。提示性质，不阻断（开发环境需要空密码兼容）。
        if self.redis_url and self.redis_url.startswith("redis://redis/"):
            import logging
            logging.getLogger(__name__).warning(
                "REDIS_URL 未包含密码字段（redis://:password@host/0）。"
                "生产环境建议启用 Redis requirepass。"
            )
        return self
    
    model_config = SettingsConfigDict(env_file=Path(__file__).parent.parent / ".env", env_nested_delimiter="__", extra="allow")

settings = Settings()
