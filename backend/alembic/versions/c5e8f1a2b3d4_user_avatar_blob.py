"""users 增加头像二进制列、MIME、版本与更新时间

Revision ID: c5e8f1a2b3d4
Revises: b1d9e4c7f2a6
Create Date: 2026-11-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e8f1a2b3d4"
down_revision: Union[str, None] = "b1d9e4c7f2a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table 在 SQLite 下走重建表，在 PG 下等价于 ALTER TABLE
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("avatar_data", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("avatar_content_type", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column(
            "avatar_version", sa.Integer(), nullable=False, server_default="0"
        ))
        batch.add_column(sa.Column("avatar_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar_updated_at")
        batch.drop_column("avatar_version")
        batch.drop_column("avatar_content_type")
        batch.drop_column("avatar_data")
