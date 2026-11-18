"""create db_backup_runs

Revision ID: c8d9e0f1a2b3
Revises: e7a8b9c0d1f2
Create Date: 2026-11-18 12:00:00.000000

升级安全说明：
- 仅新增系统级运维台账表 db_backup_runs（数据库整库备份/自动校验运行记录），
  不改动任何存量表与数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'e7a8b9c0d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'db_backup_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True,
                  comment='本次运行时间（UTC）'),
        sa.Column('trigger', sa.String(10), nullable=False, comment='auto | manual'),
        sa.Column('status', sa.String(10), nullable=False, comment='success | failed'),
        sa.Column('operator', sa.String(50), nullable=True, comment='手动=用户名；自动=system'),
        sa.Column('filename', sa.String(255), nullable=True, comment='产出的 dump 文件名'),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True, comment='pg_dump 耗时'),
        sa.Column('error', sa.Text(), nullable=True, comment='备份失败原因'),
        sa.Column('retention_deleted', sa.Integer(), nullable=True, comment='本次清理掉的过期 auto 文件数'),
        sa.Column('verify_status', sa.String(10), nullable=True, comment='passed|failed|error|skipped'),
        sa.Column('verify_error', sa.Text(), nullable=True),
        sa.Column('verify_checks', sa.JSON(), nullable=True, comment='各表行数快照'),
    )
    op.create_index('ix_db_backup_runs_id', 'db_backup_runs', ['id'])
    op.create_index('ix_db_backup_runs_created_at', 'db_backup_runs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_db_backup_runs_created_at', table_name='db_backup_runs')
    op.drop_index('ix_db_backup_runs_id', table_name='db_backup_runs')
    op.drop_table('db_backup_runs')
