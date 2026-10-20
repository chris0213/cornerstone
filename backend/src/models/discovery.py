from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint

from ..database import Base


class DiscoveryUnknownEndpoint(Base):
    """拓扑发现中无法与既有设备关联的未知接入终端
    例如交换机接入端口下学习到、但未录入资产的服务器/终端
    """
    __tablename__ = "discovery_unknown_endpoints"
    __table_args__ = (
        UniqueConstraint('device_id', 'local_interface', 'mac_address', name='uq_discovery_unknown_endpoint'),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)  # 接入设备（交换机）
    local_interface = Column(String(100), nullable=False)  # 接入端口
    mac_address = Column(String(32), nullable=False, index=True)  # 终端 MAC（归一化12位）
    ip_address = Column(String(50), nullable=True)  # 通过 ARP 关联到的 IP（可能为空）
    first_seen_at = Column(DateTime)
    last_seen_at = Column(DateTime)
