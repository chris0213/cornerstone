from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func

from ..database import Base

class Circuit(Base):
    __tablename__ = "circuits"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    provider = Column(String(100))
    type = Column(String(50))  # 互联网专线, MPLS, SD-WAN
    site_id = Column(Integer, ForeignKey("sites.id"))
    bandwidth = Column(Integer)  # Mbps
    monthly_cost = Column(Float)
    contract_start = Column(DateTime(timezone=True))
    contract_end = Column(DateTime(timezone=True), index=True)
    circuit_no = Column(String(50))
    support_phone = Column(String(20))
    public_ip = Column(String(50))
    status = Column(String(20), default="正常")
    note = Column(String(500))
    updated_by = Column(String(50))
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    # 拓扑图中专线连接的目标设备ID
    connected_device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
