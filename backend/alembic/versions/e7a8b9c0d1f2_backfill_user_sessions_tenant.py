"""回填 user_sessions 历史数据 tenant_id（按会话用户所属租户归属）

修复登录/刷新会话写入时未携带 tenant_id、全部落到默认租户 1：
demo_b（租户2）的会话被写成 tenant_id=1。会话归属影响「在线用户」
等按租户过滤的视图，错归属会导致租户1 用户看到租户2 的在线会话。

规则：
- session.user_id 能匹配到 users.id → 归属该用户当前所属租户；
- 仅回填明显错误的归属（tenant_id=1 且用户实际不属于租户1），
  不覆盖已正确归属的行。

Revision ID: e7a8b9c0d1f2
Revises: d6f9a2b3c4e5
Create Date: 2026-11-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7a8b9c0d1f2"
down_revision: Union[str, None] = "d6f9a2b3c4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 迁移前快照，便于回滚恢复
    bind.execute(sa.text(
        "CREATE TEMPORARY TABLE IF NOT EXISTS user_sessions_tenant_fix_bak AS "
        "SELECT id, tenant_id FROM user_sessions"
    ))

    bind.execute(sa.text(
        "UPDATE user_sessions SET tenant_id = ("
        "  SELECT u.tenant_id FROM users u WHERE u.id = user_sessions.user_id"
        ") WHERE tenant_id = 1"
        "  AND EXISTS ("
        "    SELECT 1 FROM users u WHERE u.id = user_sessions.user_id"
        "      AND u.tenant_id != 1)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE user_sessions SET tenant_id = ("
        "  SELECT b.tenant_id FROM user_sessions_tenant_fix_bak b"
        "  WHERE b.id = user_sessions.id"
        ") WHERE EXISTS ("
        "  SELECT 1 FROM user_sessions_tenant_fix_bak b"
        "  WHERE b.id = user_sessions.id AND b.tenant_id != user_sessions.tenant_id)"
    ))
    bind.execute(sa.text("DROP TABLE IF EXISTS user_sessions_tenant_fix_bak"))
