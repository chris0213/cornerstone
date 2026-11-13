"""M3 运维/监控/内容域 18 张表加 tenant_id（NOT NULL，回填默认租户 1）

Revision ID: f3c4d5e6a7b8
Revises: e2b3c4d5f6a7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3c4d5e6a7b8"
down_revision: Union[str, None] = "e2b3c4d5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPS_TABLES = [
    # 运维域（9）
    "backups",
    "backup_analyses",
    "backup_tasks",
    "credentials",
    "discovery_unknown_endpoints",
    "inspection_tasks",
    "inspection_results",
    "inspection_device_results",
    "device_fingerprints",
    # 监控域（5）
    "alert_rules",
    "alert_records",
    "alert_notifications",
    "link_monitor",
    "metric_samples",
    # 内容域（4）
    "knowledge_categories",
    "knowledge_articles",
    "monthly_reports",
    "ai_chat_logs",
]


def upgrade() -> None:
    for table in OPS_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(
                "tenant_id", sa.Integer(), nullable=False, server_default="1"
            ))
            batch.create_index(f"ix_{table}_tenant_id", ["tenant_id"])


def downgrade() -> None:
    for table in reversed(OPS_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_tenant_id")
            batch.drop_column("tenant_id")
