from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func

from ..database import Base


class LinkMonitor(Base):
    """链路监控数据表"""
    __tablename__ = "link_monitor"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    target_ip = Column(String(50), nullable=False)
    latency = Column(Float)  # 延迟（毫秒）
    packet_loss = Column(Float)  # 丢包率（0-100）
    status = Column(String(20), default="normal", index=True)  # normal, warning, critical
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_link_monitor_device_created', 'device_id', 'created_at'),
        {'extend_existing': True},
    )
