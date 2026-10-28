from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base

class Device(Base):
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50))  # switch, router, firewall
    brand = Column(String(50))
    vendor = Column(String(50))  # cisco_ios, cisco_nxos, huawei_vrp, h3c, juniper, fortinet
    model = Column(String(100))
    sn = Column(String(50))
    asset_tag = Column(String(50))  # 资产编号（选填）
    site_id = Column(Integer, ForeignKey("sites.id"))
    location = Column(String(255))
    mgmt_ip_id = Column(Integer, ForeignKey("ip_addresses.id"))
    rack_id = Column(Integer, ForeignKey("racks.id"))
    u_position = Column(Integer)
    u_size = Column(Integer, default=1)
    status = Column(String(20), default="active")
    purchase_date = Column(DateTime, index=True)
    warranty_end = Column(DateTime, index=True)
    purchase_amount = Column(Float)
    owner = Column(String(50))
    note = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 连接关系
    source_links = relationship("DeviceLink", foreign_keys="DeviceLink.source_device_id", back_populates="source_device")
    target_links = relationship("DeviceLink", foreign_keys="DeviceLink.target_device_id", back_populates="target_device")
    alert_rules = relationship("AlertRule", back_populates="device")
    alert_records = relationship("AlertRecord", back_populates="device")
    rack = relationship("Rack", back_populates="devices")
