"""M1 租户地基：tenants 表 + 系统/配置域加 tenant_id

- 新建 tenants 表并写入默认租户 id=1 / code='default'
- users、user_sessions、audit_logs、settings 增加 NOT NULL tenant_id（回填 1）
- roles 增加可空 tenant_id（NULL 表示平台内置角色模板）

Revision ID: d1a2b3c4e5f6
Revises: c5e8f1a2b3d4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision: str = "d1a2b3c4e5f6"
down_revision: Union[str, None] = "c5e8f1a2b3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 本批次加 NOT NULL tenant_id 的表
TENANT_TABLES = ["users", "user_sessions", "audit_logs", "settings"]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("plan", sa.String(length=50), nullable=False, server_default="standard"),
        sa.Column("contact_name", sa.String(length=50)),
        sa.Column("contact_email", sa.String(length=100)),
        sa.Column("quota", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.Column("description", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("code", name="uq_tenants_code"),
    )
    op.create_index("ix_tenants_id", "tenants", ["id"])
    op.create_index("ix_tenants_code", "tenants", ["code"])

    # 默认租户：id 固定为 1，历史数据全部回填到该租户
    op.execute(
        "INSERT INTO tenants (id, code, name, status, plan, created_at, updated_at) "
        "VALUES (1, 'default', '默认租户', 'active', 'standard', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "SELECT setval(pg_get_serial_sequence('tenants','id'), "
            "GREATEST((SELECT MAX(id) FROM tenants), 1))"
        )

    for table in TENANT_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(
                "tenant_id", sa.Integer(), nullable=False, server_default="1"
            ))
            batch.create_index(f"ix_{table}_tenant_id", ["tenant_id"])

    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("tenant_id", sa.Integer(), nullable=True))
        batch.create_index("ix_roles_tenant_id", ["tenant_id"])


def downgrade() -> None:
    with op.batch_alter_table("roles") as batch:
        batch.drop_index("ix_roles_tenant_id")
        batch.drop_column("tenant_id")

    for table in reversed(TENANT_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_tenant_id")
            batch.drop_column("tenant_id")

    op.drop_index("ix_tenants_code", table_name="tenants")
    op.drop_index("ix_tenants_id", table_name="tenants")
    op.drop_table("tenants")
