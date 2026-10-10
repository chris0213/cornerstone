"""add adaptive alerting to alert_rules and create metric_samples

Revision ID: 7d0e8fb1d835
Revises: edccf922899a
Create Date: 2026-09-07 15:45:00.000000

升级安全说明：
- alert_rules 新增 4 个可空列，存量数据不受影响；detection_mode 为 NULL 或 'static'
  时均走原有静态阈值逻辑，行为与升级前完全一致。
- metric_samples 为新增表，仅在启用 detection_mode='anomaly' 的规则后才会写入；
  默认不产生任何额外写入。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d0e8fb1d835'
down_revision: Union[str, None] = 'edccf922899a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) alert_rules 增加自适应告警相关列（全部可空，向后兼容）
    op.add_column('alert_rules', sa.Column(
        'detection_mode', sa.String(length=20), nullable=True,
        comment='检测模式：static（静态阈值）/anomaly（自适应突变检测）'))
    op.add_column('alert_rules', sa.Column(
        'baseline_window', sa.Integer(), nullable=True,
        comment='基线窗口：参与统计的样本数（默认 50）'))
    op.add_column('alert_rules', sa.Column(
        'baseline_sensitivity', sa.Float(), nullable=True,
        comment='基线敏感度：z-score 阈值（默认 3.0）'))
    op.add_column('alert_rules', sa.Column(
        'mutation_threshold', sa.Float(), nullable=True,
        comment='环比突变阈值：相对变化率（默认 0.5，即 50%）'))

    # 将存量规则显式归为 static，便于管理与展示（NULL 时代码同样按 static 处理）
    op.execute("UPDATE alert_rules SET detection_mode = 'static' WHERE detection_mode IS NULL")

    # 2) 指标采样表（滚动基线数据源）
    op.create_table(
        'metric_samples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=True),
        sa.Column('metric', sa.String(length=30), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('sampled_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_metric_samples_device_metric_time'),
                    'metric_samples', ['device_id', 'metric', 'sampled_at'], unique=False)
    op.create_index(op.f('ix_metric_samples_id'),
                    'metric_samples', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_metric_samples_id'), table_name='metric_samples')
    op.drop_index(op.f('ix_metric_samples_device_metric_time'), table_name='metric_samples')
    op.drop_table('metric_samples')

    op.drop_column('alert_rules', 'mutation_threshold')
    op.drop_column('alert_rules', 'baseline_sensitivity')
    op.drop_column('alert_rules', 'baseline_window')
    op.drop_column('alert_rules', 'detection_mode')
