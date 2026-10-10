from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.sql import func

from ..database import Base

class IPAddress(Base):
    __tablename__ = "ip_addresses"
    __table_args__ = (
        Index('ix_ip_addresses_prefix_status', 'prefix_id', 'status'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String(50), nullable=False)  # IP地址
    prefix_id = Column(Integer, ForeignKey("prefixes.id"))
    device_id = Column(Integer, ForeignKey("devices.id"))
    usage = Column(String(100))
    owner = Column(String(50))
    status = Column(String(20), default="available", index=True)  # available, assigned, reserved
    expire_at = Column(DateTime(timezone=True), nullable=True)  # 到期时间
    is_online = Column(Boolean, nullable=True)  # 是否在线
    last_seen_at = Column(DateTime(timezone=True), nullable=True)  # 最后在线时间
    scan_method = Column(String(20), nullable=True)  # 探测方式: icmp/tcp/arp/none
    open_ports = Column(String(200), nullable=True)  # 响应的TCP端口
    mac_address = Column(String(50), nullable=True)  # ARP获取的MAC
    last_scanned_at = Column(DateTime(timezone=True), nullable=True)  # 最后扫描时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
