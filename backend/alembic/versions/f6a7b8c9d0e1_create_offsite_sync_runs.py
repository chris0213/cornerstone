"""create offsite_sync_runs

Revision ID: f6a7b8c9d0e1
Revises: d0e1f2a3b4c5
Create Date: 2026-11-19 12:00:00.000000

升级安全说明：
- 仅新增系统级运维台账表 offsite_sync_runs（异地备份同步运行记录），
  不改动任何存量表与数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'offsite_sync_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True,
                  comment='本次同步时间（UTC）'),
        sa.Column('trigger', sa.String(10), nullable=False, comment='auto | manual'),
        sa.Column('status', sa.String(10), nullable=False, comment='success | failed'),
        sa.Column('operator', sa.String(50), nullable=True, comment='手动=用户名；自动=system'),
        sa.Column('target_type', sa.String(20), nullable=True, comment='rclone | rsync | sftp'),
        sa.Column('source_dir', sa.String(500), nullable=True, comment='本次同步的源目录'),
        sa.Column('duration_ms', sa.Integer(), nullable=True, comment='同步耗时'),
        sa.Column('message', sa.String(200), nullable=True, comment='结果简述'),
        sa.Column('error', sa.Text(), nullable=True, comment='失败原因（已截断脱敏）'),
    )
    op.create_index('ix_offsite_sync_runs_id', 'offsite_sync_runs', ['id'])
    op.create_index('ix_offsite_sync_runs_created_at', 'offsite_sync_runs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_offsite_sync_runs_created_at', table_name='offsite_sync_runs')
    op.drop_index('ix_offsite_sync_runs_id', table_name='offsite_sync_runs')
    op.drop_table('offsite_sync_runs')
