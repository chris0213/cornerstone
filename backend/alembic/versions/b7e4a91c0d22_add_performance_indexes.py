"""add performance indexes for hot query paths

Revision ID: b7e4a91c0d22
Revises: a1c2d3e4f5a6
Create Date: 2026-10-10 15:00:00.000000

升级安全说明：
- 仅为高频查询字段新增索引，不改动表结构与存量数据，对现有功能无影响。
- 覆盖：审计日志时间排序、告警状态+时间过滤、备份时间窗、监控设备+时间、
  IP 状态与前缀聚合、故障单状态+时间、保修/合同到期扫描、设备采购时间分段。
- if_not_exists 保证对已手工加过索引的旧库幂等。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e4a91c0d22'
down_revision: Union[str, None] = 'a1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (索引名, 表名, 列)
INDEXES = [
    ('ix_audit_logs_created_at', 'audit_logs', ['created_at']),
    ('ix_alert_records_status_created_at', 'alert_records', ['status', 'created_at']),
    ('ix_backups_created_at', 'backups', ['created_at']),
    ('ix_link_monitor_device_created', 'link_monitor', ['device_id', 'created_at']),
    ('ix_link_monitor_status', 'link_monitor', ['status']),
    ('ix_ip_addresses_status', 'ip_addresses', ['status']),
    ('ix_ip_addresses_prefix_status', 'ip_addresses', ['prefix_id', 'status']),
    ('ix_circuit_incidents_status_started', 'circuit_incidents', ['status', 'started_at']),
    ('ix_devices_warranty_end', 'devices', ['warranty_end']),
    ('ix_devices_purchase_date', 'devices', ['purchase_date']),
    ('ix_circuits_contract_end', 'circuits', ['contract_end']),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False, if_not_exists=True)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
