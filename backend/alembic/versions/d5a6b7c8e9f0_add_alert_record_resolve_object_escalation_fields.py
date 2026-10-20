"""add alert record resolve/object/escalation fields

Revision ID: d5a6b7c8e9f0
Revises: a9b8c7d6e5f4
Create Date: 2026-10-20 10:00:00.000000

升级安全说明：
- 全部新增列均为 nullable，旧代码不读写这些列时行为完全不变。
- resolved_by / resolve_note：状态流转记录处理人与处理备注。
- object_type：告警对象类型（device/circuit/prefix/ip/system），消除
  alert_records.device_id 被塞入 circuit.id 的语义过载；迁移时对存量
  circuit_expire 告警回填 object_type='circuit'。
- escalated_at：严重告警长时间未认领的升级提醒时间戳。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5a6b7c8e9f0'
down_revision: Union[str, None] = 'a9b8c7d6e5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 不支持 ALTER 添加约束，统一走 batch 模式（其他数据库等效为普通 ALTER）
    # 列间无依赖，但 FK 依赖 resolved_by 列，分两步避免拓扑排序歧义
    with op.batch_alter_table('alert_records') as batch_op:
        batch_op.add_column(sa.Column('resolved_by', sa.Integer(), nullable=True,
                                      comment='处理人'))
        batch_op.add_column(sa.Column('resolve_note', sa.Text(), nullable=True,
                                      comment='处理备注（手动处理必填）'))
        batch_op.add_column(sa.Column('object_type', sa.String(length=20), nullable=True,
                                      comment='告警对象类型：device/circuit/prefix/ip/system'))
        batch_op.add_column(sa.Column('escalated_at', sa.DateTime(), nullable=True,
                                      comment='严重告警升级提醒时间'))
    with op.batch_alter_table('alert_records') as batch_op:
        batch_op.create_foreign_key(
            'fk_alert_records_resolved_by_users', 'users',
            ['resolved_by'], ['id'],
        )
    # 存量回填：circuit_expire 告警的 device_id 实际存的是 circuit.id
    op.execute(
        "UPDATE alert_records SET object_type = 'circuit' "
        "WHERE alert_type = 'circuit_expire' AND object_type IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table('alert_records') as batch_op:
        batch_op.drop_constraint('fk_alert_records_resolved_by_users', type_='foreignkey')
        batch_op.drop_column('escalated_at')
        batch_op.drop_column('object_type')
        batch_op.drop_column('resolve_note')
        batch_op.drop_column('resolved_by')
