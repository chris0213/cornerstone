"""统一时间语义：无时区列改为 timestamptz（UTC 存储）

Revision ID: a7f3c1e9b2d4
Revises: c3d4e5f6a7b8
Create Date: 2026-11-12

背景：历史上同一批时间列混用三种语义：
- server_default=func.now()：写入值随数据库会话时区走。SQLite 的 CURRENT_TIMESTAMP
  是 UTC 挂钟；PostgreSQL 若 TimeZone=Asia/Shanghai（生产 compose 即如此），
  timestamptz 赋给 timestamp without time zone 时按会话时区落成北京挂钟。
- 应用层 datetime.now()（容器/开发机 TZ=Asia/Shanghai）：北京挂钟；
- 个别路径按 naive UTC 写入（只出现在本来就是 timestamptz 的列，不在本迁移范围）。

本迁移把剩余 16 个无时区列统一为 TIMESTAMP WITH TIME ZONE：
- 应用层写入的列按 Asia/Shanghai 解释（历史真实语义）；
- created_at/updated_at 等 server_default/onupdate 列在 PostgreSQL 生产库同样是
  北京挂钟（会话时区 Asia/Shanghai），按 Asia/Shanghai 解释；
- devices.purchase_date / warranty_end 是"日历日期"，按 UTC 解释，保证日期不偏移。

注意：若某个库是从 SQLite 迁移而来（CURRENT_TIMESTAMP 为 UTC），上述 4 个
server_default 列应改用 'utc'。执行前请用交付说明中的体检 SQL 确认。
SQLite：类型是动态的、无法 ALTER COLUMN TYPE，且应用层 UTCDateTime 已统一按 UTC
读写，故开发库直接跳过（仅开发演示用途）。
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7f3c1e9b2d4'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (表, 列, 历史语义)：bjt = 北京挂钟；utc = UTC 挂钟；date = 日历日期
COLUMNS = [
    ('alert_rules', 'muted_until', 'bjt'),
    ('alert_rules', 'created_at', 'bjt'),
    ('alert_rules', 'updated_at', 'bjt'),
    ('alert_records', 'acknowledged_at', 'bjt'),
    ('alert_records', 'resolved_at', 'bjt'),
    ('alert_records', 'escalated_at', 'bjt'),
    ('alert_records', 'created_at', 'bjt'),
    ('alert_notifications', 'sent_at', 'bjt'),
    ('alert_notifications', 'created_at', 'bjt'),
    ('metric_samples', 'sampled_at', 'bjt'),
    ('discovery_unknown_endpoints', 'first_seen_at', 'bjt'),
    ('discovery_unknown_endpoints', 'last_seen_at', 'bjt'),
    ('device_links', 'discovered_at', 'bjt'),
    ('device_links', 'verified_at', 'bjt'),
    ('devices', 'purchase_date', 'date'),
    ('devices', 'warranty_end', 'date'),
]

ZONE = {'bjt': 'Asia/Shanghai', 'utc': 'UTC', 'date': 'UTC'}


def upgrade() -> None:
    if op.get_context().dialect.name == 'sqlite':
        return
    for table, column, kind in COLUMNS:
        zone = ZONE[kind]
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f"TYPE timestamptz USING {column} AT TIME ZONE '{zone}'"
        )


def downgrade() -> None:
    if op.get_context().dialect.name == 'sqlite':
        return
    for table, column, kind in COLUMNS:
        zone = ZONE[kind]
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f"TYPE timestamp without time zone USING {column} AT TIME ZONE '{zone}'"
        )
