"""add muted_until to alert_rules

Revision ID: c3f8d21a7b45
Revises: b7e4a91c0d22
Create Date: 2026-10-10 17:00:00.000000

升级安全说明：
- 仅新增可空列 muted_until（静默截止时间），存量行为 NULL（不静默），行为完全不变。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8d21a7b45'
down_revision: Union[str, None] = 'b7e4a91c0d22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'alert_rules',
        sa.Column('muted_until', sa.DateTime(), nullable=True, comment="静默截止时间：到期前该规则不产生新告警"),
    )


def downgrade() -> None:
    op.drop_column('alert_rules', 'muted_until')
