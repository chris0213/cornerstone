"""设备表新增资产编号字段 asset_tag（选填）

Revision ID: c3d4e5f6a7b8
Revises: b8c9d0e1f2a3
Create Date: 2026-10-28
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('asset_tag', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'asset_tag')
