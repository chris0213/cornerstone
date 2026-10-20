"""add circuit_changes batch_id

Revision ID: e8f9a0b1c2d3
Revises: d5a6b7c8e9f0
Create Date: 2026-10-20 14:00:00.000000

升级安全说明：
- batch_id 为 nullable 新列，旧代码不读写时行为完全不变。
- 存量数据无法回溯操作批次，保持 NULL（视为独立批次展示）。
- 索引 idx_circuit_changes_batch_id 加速按批次聚合查询。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'd5a6b7c8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('circuit_changes') as batch_op:
        batch_op.add_column(sa.Column('batch_id', sa.String(length=36), nullable=True,
                                      comment='操作批次ID：同一次请求的多字段变更共用'))
        batch_op.create_index('idx_circuit_changes_batch_id', ['batch_id'])


def downgrade() -> None:
    with op.batch_alter_table('circuit_changes') as batch_op:
        batch_op.drop_index('idx_circuit_changes_batch_id')
        batch_op.drop_column('batch_id')
