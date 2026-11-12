"""JSON 列统一为 JSONB（PostgreSQL）

Revision ID: b1d9e4c7f2a6
Revises: a7f3c1e9b2d4
Create Date: 2026-11-12

PostgreSQL 的 json 类型不做去重、不可建 GIN 索引；统一改为 jsonb。
同时修正 inspection_tasks.tcp_ports 的历史默认值：模型此前 default 为字符串
"[22, 80, ...]"，写入后变成 JSON 字符串标量而非数组，这里规范化为数组。

SQLite：无 JSONB，应用层 JSONType 自动退回 JSON(TEXT)，本迁移跳过。
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b1d9e4c7f2a6'
down_revision: Union[str, None] = 'a7f3c1e9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    ('alert_rules', 'notification_channels'),
    ('inspection_tasks', 'tcp_ports'),
    ('inspection_results', 'ai_summary'),
    ('inspection_device_results', 'open_ports'),
    ('inspection_device_results', 'change_detail'),
    ('circuit_incidents', 'affected_sites'),
]


def upgrade() -> None:
    if op.get_context().dialect.name == 'sqlite':
        return
    for table, column in COLUMNS:
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} TYPE jsonb USING {column}::jsonb'
        )

    # tcp_ports：NULL 补默认数组；字符串标量（"\"[22, 80, ...]\""）转成真正的 JSON 数组
    op.execute(
        """
        UPDATE inspection_tasks
        SET tcp_ports = CASE
            WHEN tcp_ports IS NULL THEN '[22, 80, 443, 445, 3389]'::jsonb
            WHEN jsonb_typeof(tcp_ports) = 'string'
                 AND (tcp_ports #>> '{}') ~ '^\\s*\\[.*\\]\\s*$'
                THEN (tcp_ports #>> '{}')::jsonb
            ELSE tcp_ports
        END
        """
    )


def downgrade() -> None:
    if op.get_context().dialect.name == 'sqlite':
        return
    for table, column in COLUMNS:
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} TYPE json USING {column}::json'
        )
