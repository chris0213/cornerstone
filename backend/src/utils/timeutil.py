"""统一时间语义。

约定（全后端唯一口径）：
- 数据库存储：一律 UTC 瞬间。PostgreSQL 用 TIMESTAMP WITH TIME ZONE；
  SQLite 无真正时区类型，由 UTCDateTime 统一按 UTC 挂钟存字符串。
- 进程内运算：一律 timezone-aware 的 UTC datetime，用 utc_now() 取当前时间。
- 对外展示：仅在展示/报表分组时按需转北京时间（to_bjt / bjt_now），
  不允许把 naive 北京时间再写回数据库。

历史背景：此前代码混用 naive UTC、naive 北京时间与 func.now()，
在 SQLite（不存时区）与 PG（timestamptz）之间产生 8 小时解释偏差。
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

UTC = timezone.utc
BJT = ZoneInfo("Asia/Shanghai")


def utc_now() -> datetime:
    """当前 UTC 时间（aware）。所有 DB 写入/时间比较的统一来源。"""
    return datetime.now(UTC)


def ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """把任意来源的 datetime 归一为 aware UTC。

    - naive：视为 UTC（SQLite 不保存时区，写入时已是 UTC 挂钟）。
    - aware：转换到 UTC。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_bjt(value: Optional[datetime]) -> Optional[datetime]:
    """UTC → 北京时间（aware），仅用于展示/报表分组。"""
    value = ensure_utc(value)
    return None if value is None else value.astimezone(BJT)


def bjt_now() -> datetime:
    """当前北京时间（aware），仅用于展示相关的日期计算。"""
    return utc_now().astimezone(BJT)
