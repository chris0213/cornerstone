from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime
from ..tenant.mixin import TenantMixin


class Rack(TenantMixin, Base):
    """机柜（42U 标准）"""
    __tablename__ = "racks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), index=True)
    room = Column(String(50))
    row_position = Column(Integer, default=0)
    total_u = Column(Integer, default=42)
    status = Column(String(20), default="active")
    description = Column(String(500))
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())

    devices = relationship("Device", back_populates="rack", cascade="all, delete-orphan")
