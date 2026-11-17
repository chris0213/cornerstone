"""异地备份同步配置存取：加密存储敏感字段、校验、脱敏展示。

所有对 settings 表 offsite_sync_config 行的读写经由本模块，保证：
- 密钥/口令/私钥字段（access key、secret key、SSH 私钥）加密落库（enc: 前缀）；
- GET 只回 has_xxx + 尾 8 字符，绝不回显明文；
- 源目录限制在环境变量 OFFSITE_SYNC_ALLOWED_DIRS 白名单内（防任意目录外泄）；
- 目标类型、端口、时间等做格式校验。
"""
import json
import os
import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.setting import Setting
from src.utils.crypto import encrypt_secret, decrypt_secret
from src.utils.logger import get_logger

logger = get_logger()

OFFSITE_SYNC_KEY = "offsite_sync_config"

SECRET_ENC_PREFIX = "enc:"

# 需要加密存储的字段（云密钥、SSH 私钥等）
SECRET_FIELDS = (
    "rclone_access_key_id",
    "rclone_secret_access_key",
    "rsync_ssh_key",
    "sftp_ssh_key",
)

# 非敏感字段
PLAIN_FIELDS = (
    "enabled",
    "target_type",
    "schedule_time",
    "source_dir",
    "rclone_provider",
    "rclone_endpoint",
    "rclone_bucket",
    "rclone_region",
    "rclone_prefix",
    "rsync_host",
    "rsync_port",
    "rsync_user",
    "rsync_remote_path",
    "sftp_host",
    "sftp_port",
    "sftp_user",
    "sftp_remote_path",
)

TARGET_TYPES = ("rclone", "rsync", "sftp")
RCLONE_PROVIDERS = ("s3", "minio", "oss", "cos")
DEFAULT_SOURCE_DIR = "/opt/cornerstone/db_backups"

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")


def get_allowed_source_dirs() -> set[str]:
    """允许作为同步源的目录白名单：默认 db_backups，可用环境变量扩展（逗号分隔）。

    关键安全控制：不限制源目录的话，超管可把 /etc、/root、卷内任意路径外传到
    攻击者主机 —— 这是数据外泄面。故源目录必须落在白名单内。
    """
    dirs = {DEFAULT_SOURCE_DIR}
    extra = os.environ.get("OFFSITE_SYNC_ALLOWED_DIRS", "")
    for d in extra.split(","):
        d = d.strip()
        if d:
            dirs.add(d)
    return dirs


def _validate_port(port, name: str) -> int:
    try:
        p = int(port)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 端口非法")
    if p < 1 or p > 65535:
        raise ValueError(f"{name} 端口必须在 1-65535")
    return p


def _validate_host(host: str, name: str) -> str:
    host = (host or "").strip()
    if not host:
        raise ValueError(f"{name} 主机不能为空")
    if not _HOST_RE.match(host):
        raise ValueError(f"{name} 主机格式非法: {host}")
    return host


def _validate_path(path: str, name: str) -> str:
    """远程路径/前缀：禁止 shell 元字符与路径穿越，仅允许安全字符集。"""
    path = (path or "").strip()
    if not path:
        raise ValueError(f"{name} 不能为空")
    if ".." in path:
        raise ValueError(f"{name} 不允许包含 '..'")
    if not re.match(r"^[A-Za-z0-9._/-]{1,255}$", path):
        raise ValueError(f"{name} 含非法字符（仅允许字母数字与 . _ / -）")
    return path


def validate_config(config: dict) -> dict:
    """校验并规范化配置，返回规范化后的 dict；非法抛 ValueError。

    仅在 enabled=True 时强制校验对应目标类型的必填项（关闭时可保存半成品草稿）。
    """
    target_type = (config.get("target_type") or "rclone").strip()
    if target_type not in TARGET_TYPES:
        raise ValueError(f"不支持的同步类型: {target_type}（仅 {', '.join(TARGET_TYPES)}）")

    schedule_time = (config.get("schedule_time") or "").strip()
    if schedule_time and not _TIME_RE.match(schedule_time):
        raise ValueError("定时时间格式应为 HH:MM")

    source_dir = (config.get("source_dir") or DEFAULT_SOURCE_DIR).strip()
    if source_dir not in get_allowed_source_dirs():
        raise ValueError(
            f"源目录 {source_dir} 不在允许列表内（允许: {', '.join(sorted(get_allowed_source_dirs()))}）"
        )

    out = dict(config)
    out["target_type"] = target_type
    out["schedule_time"] = schedule_time or "04:00"
    out["source_dir"] = source_dir

    if not config.get("enabled"):
        # 关闭状态：只做基础规范化，不强校验目标细节
        return out

    if target_type == "rclone":
        provider = (config.get("rclone_provider") or "minio").strip()
        if provider not in RCLONE_PROVIDERS:
            raise ValueError(f"rclone provider 非法: {provider}（仅 {', '.join(RCLONE_PROVIDERS)}）")
        endpoint = (config.get("rclone_endpoint") or "").strip()
        if endpoint:
            parsed = urlparse(endpoint)
            if parsed.scheme not in ("https", "http"):
                raise ValueError("rclone endpoint 必须是 http(s) URL")
        if not (config.get("rclone_bucket") or "").strip():
            raise ValueError("rclone bucket 不能为空")
        if not (config.get("rclone_access_key_id") or "").strip():
            raise ValueError("rclone access_key_id 不能为空")
        if not (config.get("rclone_secret_access_key") or "").strip():
            raise ValueError("rclone secret_access_key 不能为空")
        out["rclone_provider"] = provider
        out["rclone_bucket"] = (config.get("rclone_bucket") or "").strip()
        out["rclone_prefix"] = _validate_path(config.get("rclone_prefix") or "cornerstone-db", "rclone prefix")
    elif target_type == "rsync":
        out["rsync_host"] = _validate_host(config.get("rsync_host"), "rsync")
        out["rsync_port"] = _validate_port(config.get("rsync_port") or 22, "rsync")
        if not (config.get("rsync_user") or "").strip():
            raise ValueError("rsync 用户名不能为空")
        out["rsync_remote_path"] = _validate_path(config.get("rsync_remote_path"), "rsync 远程路径")
        if not (config.get("rsync_ssh_key") or "").strip():
            raise ValueError("rsync 需要 SSH 私钥（本版仅支持密钥认证）")
    elif target_type == "sftp":
        out["sftp_host"] = _validate_host(config.get("sftp_host"), "sftp")
        out["sftp_port"] = _validate_port(config.get("sftp_port") or 22, "sftp")
        if not (config.get("sftp_user") or "").strip():
            raise ValueError("sftp 用户名不能为空")
        out["sftp_remote_path"] = _validate_path(config.get("sftp_remote_path"), "sftp 远程路径")
        if not (config.get("sftp_ssh_key") or "").strip():
            raise ValueError("sftp 需要 SSH 私钥（本版仅支持密钥认证）")

    return out


def encrypt_config(config: dict) -> dict:
    out = dict(config)
    for f in SECRET_FIELDS:
        v = out.get(f)
        if v and not str(v).startswith(SECRET_ENC_PREFIX):
            out[f] = encrypt_secret(str(v))
    return out


def decrypt_config(config: dict) -> dict:
    out = dict(config)
    for f in SECRET_FIELDS:
        v = out.get(f)
        if v and str(v).startswith(SECRET_ENC_PREFIX):
            out[f] = decrypt_secret(str(v))
    return out


def mask_config_for_display(config: dict) -> dict:
    """GET 用：敏感字段只回 has_xxx + 尾 8 字符，不回明文。"""
    out: dict = {}
    for f in PLAIN_FIELDS:
        out[f] = config.get(f)
    for f in SECRET_FIELDS:
        raw = config.get(f) or ""
        if raw:
            plain = decrypt_secret(raw) if raw.startswith(SECRET_ENC_PREFIX) else raw
            out[f"has_{f}"] = True
            out[f"{f}_tail"] = (plain[-8:] if len(plain) > 8 else plain)
        else:
            out[f"has_{f}"] = False
            out[f"{f}_tail"] = ""
    return out


async def load_stored_config(db: AsyncSession) -> dict:
    result = await db.execute(select(Setting).filter(Setting.key == OFFSITE_SYNC_KEY))
    setting = result.scalars().first()
    if not setting:
        return {}
    try:
        data = json.loads(setting.value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("[异地同步] settings.offsite_sync_config 非合法 JSON，按空配置处理")
        return {}


async def save_stored_config(db: AsyncSession, config: dict) -> None:
    encrypted = encrypt_config(config)
    result = await db.execute(select(Setting).filter(Setting.key == OFFSITE_SYNC_KEY))
    setting = result.scalars().first()
    config_json = json.dumps(encrypted, ensure_ascii=False)
    if setting:
        setting.value = config_json
    else:
        db.add(Setting(key=OFFSITE_SYNC_KEY, value=config_json))
    await db.commit()


def get_effective_config(db_config: dict) -> dict:
    """合并默认值后的有效配置（敏感字段解密，供执行/测试用）。"""
    merged = {
        "enabled": bool(db_config.get("enabled", False)),
        "target_type": db_config.get("target_type") or "rclone",
        "schedule_time": db_config.get("schedule_time") or "04:00",
        "source_dir": db_config.get("source_dir") or DEFAULT_SOURCE_DIR,
    }
    for f in PLAIN_FIELDS:
        if f not in merged:
            merged[f] = db_config.get(f)
    return decrypt_config({**db_config, **merged})
