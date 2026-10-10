"""add ai_summary to inspection_results

Revision ID: 8c7cdaf81911
Revises: 2733fdbc9397
Create Date: 2026-09-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c7cdaf81911'
down_revision: Union[str, None] = '2733fdbc9397'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('inspection_results', sa.Column('ai_summary', sa.JSON(), nullable=True, comment='AI异常二次研判结论'))


def downgrade() -> None:
    op.drop_column('inspection_results', 'ai_summary')
