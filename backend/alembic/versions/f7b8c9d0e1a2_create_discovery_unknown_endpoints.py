"""create discovery_unknown_endpoints

Revision ID: f7b8c9d0e1a2
Revises: e1f2a3b4c5d6
Create Date: 2026-10-19 12:00:00.000000

升级安全说明：
- 仅新增表 discovery_unknown_endpoints（拓扑发现的未知接入终端记录），不影响存量数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7b8c9d0e1a2'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'discovery_unknown_endpoints',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id'), nullable=False,
                  comment='接入设备（交换机）'),
        sa.Column('local_interface', sa.String(100), nullable=False, comment='接入端口'),
        sa.Column('mac_address', sa.String(32), nullable=False, comment='终端MAC（归一化12位）'),
        sa.Column('ip_address', sa.String(50), nullable=True, comment='通过ARP关联到的IP'),
        sa.Column('first_seen_at', sa.DateTime(), nullable=True, comment='首次发现时间'),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True, comment='最后发现时间'),
        sa.UniqueConstraint('device_id', 'local_interface', 'mac_address',
                            name='uq_discovery_unknown_endpoint'),
    )
    op.create_index('ix_discovery_unknown_endpoints_id', 'discovery_unknown_endpoints', ['id'])
    op.create_index('ix_discovery_unknown_endpoints_mac_address', 'discovery_unknown_endpoints', ['mac_address'])


def downgrade() -> None:
    op.drop_index('ix_discovery_unknown_endpoints_mac_address', table_name='discovery_unknown_endpoints')
    op.drop_index('ix_discovery_unknown_endpoints_id', table_name='discovery_unknown_endpoints')
    op.drop_table('discovery_unknown_endpoints')
