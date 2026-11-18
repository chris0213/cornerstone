"""add sha256 to db_backup_runs

Revision ID: d0e1f2a3b4c5
Revises: c8d9e0f1a2b3
Create Date: 2026-11-18 13:00:00.000000

升级安全说明：
- 仅给 db_backup_runs 增加可空列 sha256（备份文件内容指纹），不动存量数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('db_backup_runs', sa.Column('sha256', sa.String(64), nullable=True,
                  comment='产出时文件内容 SHA-256 指纹'))


def downgrade() -> None:
    op.drop_column('db_backup_runs', 'sha256')
