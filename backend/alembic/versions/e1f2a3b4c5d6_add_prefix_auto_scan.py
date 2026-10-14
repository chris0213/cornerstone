"""add custom_scan_ports + auto_scan fields to prefixes

Revision ID: e1f2a3b4c5d6
Revises: c3f8d21a7b45
Create Date: 2026-10-14 10:00:00

- custom_scan_ports: 自定义 TCP 扫描端口组，逗号分隔，空则用默认
- auto_scan_enabled: 自动定时扫描开关
- scan_cron: 自动扫描 cron 表达式（默认每 6 小时）
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prefixes", sa.Column("custom_scan_ports", sa.String(length=200), nullable=True, comment="自定义TCP扫描端口组，逗号分隔"))
    op.add_column("prefixes", sa.Column("auto_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否启用自动定时扫描"))
    op.add_column("prefixes", sa.Column("scan_cron", sa.String(length=50), nullable=False, server_default="0 */6 * * *", comment="自动扫描cron表达式"))


def downgrade() -> None:
    op.drop_column("prefixes", "scan_cron")
    op.drop_column("prefixes", "auto_scan_enabled")
    op.drop_column("prefixes", "custom_scan_ports")
