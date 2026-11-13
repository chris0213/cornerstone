"""回填 audit_logs 历史数据 tenant_id（按操作用户所属租户归属）

修复登录日志写入时未携带 tenant_id、全部落到默认租户 1 导致的跨租户泄漏：
demo_b（租户2）的登录日志被写成 tenant_id=1，租户1 用户反而可见。

规则：
- audit_logs.user 能匹配到 users.username → 归属该用户当前所属租户；
- 匹配不到（已删除用户、匿名操作）→ 保留平台级默认租户 1，供超管审计；
- 仅回填明显错误的归属（tenant_id=1 且用户实际不属于租户1），不覆盖
  已正确归属的行。

Revision ID: d6f9a2b3c4e5
Revises: c5e8f1a2b3d4
Create Date: 2026-11-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d6f9a2b3c4e5"
down_revision: Union[str, None] = "f3c4d5e6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 迁移前快照，便于回滚核对（临时表，迁移事务结束自动清理语义由 DB 决定）
    bind.execute(sa.text(
        "CREATE TEMPORARY TABLE IF NOT EXISTS audit_logs_tenant_fix_bak AS "
        "SELECT id, tenant_id FROM audit_logs"
    ))

    # 仅修正「错误归属到默认租户1」的行：操作用户真实租户 != 1 才回填
    bind.execute(sa.text(
        "UPDATE audit_logs SET tenant_id = ("
        "  SELECT u.tenant_id FROM users u WHERE u.username = audit_logs.user"
        ") WHERE tenant_id = 1"
        "  AND EXISTS ("
        "    SELECT 1 FROM users u WHERE u.username = audit_logs.user"
        "      AND u.tenant_id != 1)"
    ))


def downgrade() -> None:
    # 按快照恢复 tenant_id（仅恢复本次迁移触碰过的行）
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE audit_logs SET tenant_id = ("
        "  SELECT b.tenant_id FROM audit_logs_tenant_fix_bak b"
        "  WHERE b.id = audit_logs.id"
        ") WHERE EXISTS ("
        "  SELECT 1 FROM audit_logs_tenant_fix_bak b"
        "  WHERE b.id = audit_logs.id AND b.tenant_id != audit_logs.tenant_id)"
    ))
    bind.execute(sa.text("DROP TABLE IF EXISTS audit_logs_tenant_fix_bak"))
