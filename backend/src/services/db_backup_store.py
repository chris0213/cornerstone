"""数据库 dump 备份调度配置存取：settings 表 db_backup_config 行的校验/读写/默认值。

字段（均非敏感，明文存即可）：
- enabled: 是否启用应用内每日定时备份（默认 False，避免装上即跑）；
- schedule_time: 每日执行时刻 HH:MM（Asia/Shanghai，与异地同步/设备备份一致）；
- retention_days: __auto 备份保留天数（<=0 表示不按时间清理）；
- keep_last: 至少保留最近 N 个 __auto 文件（<=0 表示不保底）；
- auto_verify: 每次定时备份成功后，自动对刚产出的 dump 跑一次隔离库校验，失败则告警。

注意：手动备份（__manual 及历史无标记文件）永不被保留策略删除，故此处无需 manual 开关。
"""
import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.setting import Setting
from src.utils.logger import get_logger

logger = get_logger()

DB_BACKUP_KEY = "db_backup_config"

DEFAULTS = {
    "enabled": False,
    "schedule_time": "03:30",
    "retention_days": 30,
    "keep_last": 7,
    "auto_verify": False,
}

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _non_neg_int(v, name: str) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是整数")
    if n < 0:
        raise ValueError(f"{name} 不能为负")
    return n


def validate_config(config: dict) -> dict:
    """校验并规范化配置，返回规范化后的 dict；非法抛 ValueError。"""
    schedule_time = (config.get("schedule_time") or "").strip()
    if not _TIME_RE.match(schedule_time):
        raise ValueError("定时时间格式应为 HH:MM（24 小时制）")

    out = {
        "enabled": bool(config.get("enabled", False)),
        "schedule_time": schedule_time,
        "retention_days": _non_neg_int(config.get("retention_days", DEFAULTS["retention_days"]), "保留天数"),
        "keep_last": _non_neg_int(config.get("keep_last", DEFAULTS["keep_last"]), "至少保留个数"),
        "auto_verify": bool(config.get("auto_verify", False)),
    }
    return out


async def load_stored_config(db: AsyncSession) -> dict:
    result = await db.execute(select(Setting).filter(Setting.key == DB_BACKUP_KEY))
    setting = result.scalars().first()
    if not setting:
        return {}
    try:
        data = json.loads(setting.value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("[数据库备份] settings.db_backup_config 非合法 JSON，按空配置处理")
        return {}


async def save_stored_config(db: AsyncSession, config: dict) -> None:
    result = await db.execute(select(Setting).filter(Setting.key == DB_BACKUP_KEY))
    setting = result.scalars().first()
    config_json = json.dumps(config, ensure_ascii=False)
    if setting:
        setting.value = config_json
    else:
        db.add(Setting(key=DB_BACKUP_KEY, value=config_json))
    await db.commit()


def get_effective_config(db_config: dict) -> dict:
    """合并默认值后的有效配置（供执行/调度用）。"""
    merged = dict(DEFAULTS)
    merged.update(db_config or {})
    return {
        "enabled": bool(merged.get("enabled", False)),
        "schedule_time": merged.get("schedule_time") or DEFAULTS["schedule_time"],
        "retention_days": merged.get("retention_days", DEFAULTS["retention_days"]),
        "keep_last": merged.get("keep_last", DEFAULTS["keep_last"]),
        "auto_verify": bool(merged.get("auto_verify", False)),
    }
