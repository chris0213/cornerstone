"""knowledge soft-delete, updated_by, categories table

Revision ID: f2a3b4c5d6e7
Revises: e8f9a0b1c2d3
Create Date: 2026-10-21 11:05:00.000000

升级安全说明：
- knowledge_articles 新增 deleted_at / updated_by 两列均为 nullable，旧代码不读写时行为不变。
- 新增 knowledge_categories 表并预置 5 个分类（故障处理/配置手册/操作SOP/常见问题/其他）。
- 存量文章的 category 值回填进分类表（DISTINCT 追加，仅插入不存在的名称，不丢值）。
- downgrade 可完全回滚：删两列与索引、删分类表（存量文章 category 字段不受影响）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRESET_CATEGORIES = [
    ("故障处理", 1),
    ("配置手册", 2),
    ("操作SOP", 3),
    ("常见问题", 4),
    ("其他", 5),
]


def upgrade() -> None:
    # 1) 分类表 + 预置分类
    op.create_table(
        'knowledge_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_knowledge_categories_name'),
    )
    op.create_index(op.f('ix_knowledge_categories_id'), 'knowledge_categories', ['id'], unique=False)
    op.create_index(op.f('ix_knowledge_categories_name'), 'knowledge_categories', ['name'], unique=True)

    bind = op.get_bind()
    for name, sort_order in PRESET_CATEGORIES:
        # 兼容 SQL：仅当名称不存在时插入（不用 INSERT OR IGNORE，保证 MySQL/Postgres/SQLite 通用）
        exists = bind.execute(
            sa.text("SELECT id FROM knowledge_categories WHERE name = :name"),
            {"name": name},
        ).first()
        if not exists:
            bind.execute(
                sa.text(
                    "INSERT INTO knowledge_categories (name, sort_order) VALUES (:name, :sort_order)"
                ),
                {"name": name, "sort_order": sort_order},
            )

    # 2) 文章表加列
    with op.batch_alter_table('knowledge_articles') as batch_op:
        batch_op.add_column(sa.Column('updated_by', sa.String(length=50), nullable=True,
                                      comment='最后修改人（用户名）'))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True,
                                      comment='软删除标记'))
        batch_op.create_index('ix_knowledge_articles_deleted_at', ['deleted_at'])

    # 3) 存量文章 category 回填进分类表（DISTINCT 追加，不丢值；忽略空值/空串）
    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT category FROM knowledge_articles "
            "WHERE category IS NOT NULL AND TRIM(category) <> ''"
        )
    ).fetchall()
    for (name,) in rows:
        exists = bind.execute(
            sa.text("SELECT id FROM knowledge_categories WHERE name = :name"),
            {"name": name},
        ).first()
        if not exists:
            bind.execute(
                sa.text("INSERT INTO knowledge_categories (name, sort_order) VALUES (:name, 99)"),
                {"name": name},
            )


def downgrade() -> None:
    with op.batch_alter_table('knowledge_articles') as batch_op:
        batch_op.drop_index('ix_knowledge_articles_deleted_at')
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('updated_by')
    op.drop_index(op.f('ix_knowledge_categories_name'), table_name='knowledge_categories')
    op.drop_index(op.f('ix_knowledge_categories_id'), table_name='knowledge_categories')
    op.drop_table('knowledge_categories')
