"""通知渠道配置存取中心：加密存储、校验、解密读取。

所有对 settings 表 notification_settings 行的读写必须经由本模块，
保证密钥字段（webhook URL / SMTP 密码）加密落库、读取处统一解密。
"""
import json
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.setting import Setting
from src.config import settings
from src.utils.crypto import encrypt_password, decrypt_password
from src.utils.logger import get_logger

logger = get_logger()

NOTIFICATION_SETTINGS_KEY = "notification_settings"

# 密文前缀：与 SSO/LDAC 模块一致（system.py SECRET_ENC_PREFIX）
SECRET_ENC_PREFIX = "enc:"

# 需要加密存储的字段（webhook URL 含 access_token 凭据，一并加密）
SECRET_FIELDS = (
    "dingtalk_webhook_url",
    "wechat_webhook_url",
    "feishu_webhook_url",
    "smtp_password",
)

# 非敏感字段原样存储
PLAIN_FIELDS = (
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_from_email",
    "smtp_security",
    "channel_enabled",
)

# 默认渠道启用开关：全量 True 保持既有行为（未配置时所有渠道照发）
DEFAULT_CHANNEL_ENABLED = {
    "dingtalk": True,
    "wechat": True,
    "feishu": True,
    "email": True,
}

# webhook 域名白名单（可经环境变量 NOTIFICATION_WEBHOOK_ALLOWED_HOSTS 扩展，逗号分隔）
_DEFAULT_ALLOWED_HOSTS = {
    "oapi.dingtalk.com",       # 钉钉
    "qyapi.weixin.qq.com",     # 企业微信
    "open.feishu.cn",          # 飞书
    "open.larksuite.com",      # 飞书海外
}


def get_allowed_webhook_hosts() -> set[str]:
    """域名白名单：默认三家 + 环境变量扩展。"""
    import os
    hosts = set(_DEFAULT_ALLOWED_HOSTS)
    extra = os.environ.get("NOTIFICATION_WEBHOOK_ALLOWED_HOSTS", "")
    for h in extra.split(","):
        h = h.strip().lower()
        if h:
            hosts.add(h)
    return hosts


def validate_webhook_url(url: str, channel: str) -> str:
    """校验 webhook URL：必须 https 且域名在白名单内。

    返回规范化后的 URL；不合法抛 ValueError（调用方转 HTTP 422/400）。
    """
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"{channel} Webhook 必须使用 https 协议")
    host = (parsed.hostname or "").lower()
    if host not in get_allowed_webhook_hosts():
        raise ValueError(
            f"{channel} Webhook 域名 {host or '(空)'} 不在白名单内"
            f"（允许: {', '.join(sorted(get_allowed_webhook_hosts()))}）"
        )
    return url


def encrypt_config(config: dict) -> dict:
    """对 SECRET_FIELDS 加密（幂等：已带 enc: 前缀的跳过）。"""
    out = dict(config)
    for f in SECRET_FIELDS:
        v = out.get(f)
        if v and not str(v).startswith(SECRET_ENC_PREFIX):
            out[f] = SECRET_ENC_PREFIX + encrypt_password(str(v))
    return out


def decrypt_config(config: dict) -> dict:
    """解密 SECRET_FIELDS，返回含明文的完整配置 dict（仅供发送/测试用）。"""
    out = dict(config)
    for f in SECRET_FIELDS:
        v = out.get(f)
        if v and str(v).startswith(SECRET_ENC_PREFIX):
            out[f] = decrypt_password(str(v)[len(SECRET_ENC_PREFIX):])
    return out


def mask_config_for_display(config: dict) -> dict:
    """GET 用：密钥字段只回 has_xxx 布尔 + 尾 8 字符辅助识别，不回原文。"""
    out: dict = {}
    for f in SECRET_FIELDS:
        raw = config.get(f) or ""
        has_key = f"has_{f}"
        tail_key = f"{f}_tail"
        if raw:
            # tail 必须取明文尾部（用于人工识别），密文 token 尾部无意义
            try:
                plain = decrypt_config({f: raw})[f] or ""
            except Exception:
                plain = raw[len(SECRET_ENC_PREFIX):] if raw.startswith(SECRET_ENC_PREFIX) else raw
            out[has_key] = True
            out[tail_key] = plain[-8:] if len(plain) > 8 else plain
        else:
            out[has_key] = False
            out[tail_key] = ""
    for f in PLAIN_FIELDS:
        if f in config:
            out[f] = config.get(f)
    return out


async def load_stored_config(db: AsyncSession) -> dict:
    """读取库中原始配置（密文字段保持密文），无配置返回空 dict。"""
    result = await db.execute(select(Setting).filter(Setting.key == NOTIFICATION_SETTINGS_KEY))
    setting = result.scalars().first()
    if not setting:
        return {}
    try:
        data = json.loads(setting.value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("[通知配置] settings 表 notification_settings 值不是合法 JSON，按空配置处理")
        return {}


async def save_stored_config(db: AsyncSession, config: dict) -> None:
    """加密后写入/更新 settings 表（调用方负责审计与提交时机外的日志）。"""
    encrypted = encrypt_config(config)
    result = await db.execute(select(Setting).filter(Setting.key == NOTIFICATION_SETTINGS_KEY))
    setting = result.scalars().first()
    config_json = json.dumps(encrypted, ensure_ascii=False)
    if setting:
        setting.value = config_json
    else:
        db.add(Setting(key=NOTIFICATION_SETTINGS_KEY, value=config_json))
    await db.commit()


async def get_notification_config(db: AsyncSession) -> dict:
    """供发送方使用的完整明文配置（库值 + 环境变量回落 + 解密 + 默认开关）。

    替代原 AlertService._get_notification_config / CircuitExpireService._get_notification_config。
    """
    stored = await load_stored_config(db)
    config = decrypt_config(stored)

    merged = {
        "dingtalk_webhook_url": config.get("dingtalk_webhook_url") or settings.notification.dingtalk_webhook_url or "",
        "wechat_webhook_url": config.get("wechat_webhook_url") or settings.notification.wechat_webhook_url or "",
        "feishu_webhook_url": config.get("feishu_webhook_url") or settings.notification.feishu_webhook_url or "",
        "smtp_host": config.get("smtp_host") or settings.notification.smtp_host,
        "smtp_port": config.get("smtp_port") or settings.notification.smtp_port,
        "smtp_username": config.get("smtp_username") or settings.notification.smtp_username,
        "smtp_password": config.get("smtp_password") or settings.notification.smtp_password,
        "smtp_from_email": config.get("smtp_from_email") or settings.notification.smtp_from_email,
        "smtp_security": config.get("smtp_security") or "starttls",
        "channel_enabled": {**DEFAULT_CHANNEL_ENABLED, **(config.get("channel_enabled") or {})},
    }
    return merged


def is_channel_enabled(config: dict, channel: str) -> bool:
    """渠道启用开关判断（未配置默认启用，保持既有行为）。"""
    return bool((config.get("channel_enabled") or {}).get(channel, True))


def is_email_ready(config: dict) -> bool:
    """邮件渠道四要素是否齐全。"""
    return all([
        config.get("smtp_host"),
        config.get("smtp_username"),
        config.get("smtp_password"),
        config.get("smtp_from_email"),
    ])
