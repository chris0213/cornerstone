"""add last_tested_at and last_test_status to credentials

Revision ID: a9b8c7d6e5f4
Revises: f7b8c9d0e1a2
Create Date: 2026-10-20 10:00:00.000000

升级安全说明：
- 仅新增可空列 last_tested_at / last_test_status，存量行为 NULL（从未测试），行为完全不变。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = 'f7b8c9d0e1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'credentials',
        sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True, comment="最近一次测试连接时间（UTC）"),
    )
    op.add_column(
        'credentials',
        sa.Column('last_test_status', sa.String(20), nullable=True, comment="最近一次测试连接结果：success / failed"),
    )


def downgrade() -> None:
    op.drop_column('credentials', 'last_test_status')
    op.drop_column('credentials', 'last_tested_at')
