"""create ai_chat_logs table

Revision ID: a1c2d3e4f5a6
Revises: 7d0e8fb1d835
Create Date: 2026-09-07 17:00:00.000000

升级安全说明：
- 新增 ai_chat_logs 表，用于持久化 AI 运维助手的聊天日志（仅本人与超级管理员可见，保留 30 天）。
- 仅新增表，不改动任何存量表结构，对现有功能无影响。
- 回答文案在写入前已做脱敏（IP / MAC / 邮箱），不存储底层查询结果明细行，避免 PII 落入日志。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c2d3e4f5a6'
down_revision: Union[str, None] = '7d0e8fb1d835'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_chat_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=False),
        sa.Column('data_type', sa.String(length=50), nullable=True),
        sa.Column('client_ip', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_chat_logs_user_id'), 'ai_chat_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_ai_chat_logs_data_type'), 'ai_chat_logs', ['data_type'], unique=False)
    op.create_index(op.f('ix_ai_chat_logs_created_at'), 'ai_chat_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_ai_chat_logs_id'), 'ai_chat_logs', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_chat_logs_id'), table_name='ai_chat_logs')
    op.drop_index(op.f('ix_ai_chat_logs_created_at'), table_name='ai_chat_logs')
    op.drop_index(op.f('ix_ai_chat_logs_data_type'), table_name='ai_chat_logs')
    op.drop_index(op.f('ix_ai_chat_logs_user_id'), table_name='ai_chat_logs')
    op.drop_table('ai_chat_logs')
