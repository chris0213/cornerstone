"""统一时间语义：无时区列改为 timestamptz（UTC 存储）

Revision ID: a7f3c1e9b2d4
Revises: c3d4e5f6a7b8
Create Date: 2026-11-12

背景：历史上同一批时间列混用三种语义：
- server_default=func.now()：SQLite 为 UTC 挂钟；
- 应用层 datetime.now()（容器/开发机 TZ=Asia/Shanghai）：北京挂钟；
- 个别路径按 naive UTC 写入。

本迁移把剩余 16 个无时区列统一为 TIMESTAMP WITH TIME ZONE：
- 应用层写入的列按 Asia/Shanghai 解释（历史真实语义）；
- server_default/onupdate 生成的 created_at/updated_at 按 UTC 解释；
- devices.purchase_date / warranty_end 是"日历日期"，按 UTC 解释，保证日期不偏移。

SQLite：类型是动态的、无法 ALTER COLUMN TYPE，且应用层 UTCDateTime 已统一按 UTC
读写，故开发库直接跳过（仅开发演示用途）。
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7f3c1e9b2d4'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (表, 列, 历史语义)：bjt = 应用层北京挂钟；utc = 数据库 UTC 挂钟；date = 日历日期
COLUMNS = [
    ('alert_rules', 'muted_until', 'bjt'),
    ('alert_rules', 'created_at', 'utc'),
    ('alert_rules', 'updated_at', 'utc'),
    ('alert_records', 'acknowledged_at', 'bjt'),
    ('alert_records', 'resolved_at', 'bjt'),
    ('alert_records', 'escalated_at', 'bjt'),
    ('alert_records', 'created_at', 'utc'),
    ('alert_notifications', 'sent_at', 'bjt'),
    ('alert_notifications', 'created_at', 'utc'),
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
