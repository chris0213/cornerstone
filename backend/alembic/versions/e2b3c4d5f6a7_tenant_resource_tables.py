"""M2 资源域 13 张表加 tenant_id（NOT NULL，回填默认租户 1）

Revision ID: e2b3c4d5f6a7
Revises: d1a2b3c4e5f6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2b3c4d5f6a7"
down_revision: Union[str, None] = "d1a2b3c4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESOURCE_TABLES = [
    "sites",
    "racks",
    "circuits",
    "circuit_changes",
    "circuit_incidents",
    "circuit_incident_logs",
    "aggregates",
    "prefixes",
    "ip_addresses",
    "vlans",
    "vlan_groups",
    "devices",
    "device_links",
]


def upgrade() -> None:
    for table in RESOURCE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(
                "tenant_id", sa.Integer(), nullable=False, server_default="1"
            ))
            batch.create_index(f"ix_{table}_tenant_id", ["tenant_id"])


def downgrade() -> None:
    for table in reversed(RESOURCE_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_tenant_id")
            batch.drop_column("tenant_id")
