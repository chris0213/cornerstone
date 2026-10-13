"""create knowledge_articles table

Revision ID: d4e5f6a7b8c9
Revises: c3f8d21a7b45
Create Date: 2026-10-13 16:00:00.000000

升级安全说明：
- 新增 knowledge_articles 表，用于知识库文章（运维经验沉淀）。
- 仅新增表，不改动任何存量表结构，对现有功能无影响。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3f8d21a7b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'knowledge_articles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('tags', sa.String(length=200), nullable=True),
        sa.Column('summary', sa.String(length=500), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('author', sa.String(length=50), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=True),
        sa.Column('view_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_articles_id'), 'knowledge_articles', ['id'], unique=False)
    op.create_index(op.f('ix_knowledge_articles_title'), 'knowledge_articles', ['title'], unique=False)
    op.create_index(op.f('ix_knowledge_articles_category'), 'knowledge_articles', ['category'], unique=False)
    op.create_index(op.f('ix_knowledge_articles_created_at'), 'knowledge_articles', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_knowledge_articles_created_at'), table_name='knowledge_articles')
    op.drop_index(op.f('ix_knowledge_articles_category'), table_name='knowledge_articles')
    op.drop_index(op.f('ix_knowledge_articles_title'), table_name='knowledge_articles')
    op.drop_index(op.f('ix_knowledge_articles_id'), table_name='knowledge_articles')
    op.drop_table('knowledge_articles')
