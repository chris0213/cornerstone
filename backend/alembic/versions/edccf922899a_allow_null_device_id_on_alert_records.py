"""allow null device_id on alert_records

Revision ID: edccf922899a
Revises: 8c7cdaf81911
Create Date: 2026-09-07 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'edccf922899a'
down_revision: Union[str, None] = '8c7cdaf81911'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('alert_records', 'device_id',
                    existing_type=sa.Integer(),
                    nullable=True)


def downgrade() -> None:
    conn = op.get_bind()
    n = conn.execute(sa.text("SELECT COUNT(*) FROM alert_records WHERE device_id IS NULL")).scalar()
    if n and n > 0:
        raise RuntimeError(
            f"无法回滚：alert_records 存在 {n} 条 device_id 为空的记录，请先处理这些记录后再回滚"
        )
    op.alter_column('alert_records', 'device_id',
                    existing_type=sa.Integer(),
                    nullable=False)
