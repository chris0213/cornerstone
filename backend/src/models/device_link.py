from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime
from ..tenant.mixin import TenantMixin

class DeviceLink(TenantMixin, Base):
    __tablename__ = "device_links"
    
    id = Column(Integer, primary_key=True, index=True)
    source_device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    source_interface = Column(String(100))
    target_device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    target_interface = Column(String(100))
    link_type = Column(String(20), nullable=False, default="manual")
    confidence = Column(Integer, default=100)
    discovered_at = Column(UTCDateTime)
    verified_at = Column(UTCDateTime)
    note = Column(Text)
    
    source_circuit_id = Column(Integer, ForeignKey("circuits.id"), nullable=True)
    target_circuit_id = Column(Integer, ForeignKey("circuits.id"), nullable=True)
    
    source_device = relationship("Device", foreign_keys=[source_device_id], back_populates="source_links")
    target_device = relationship("Device", foreign_keys=[target_device_id], back_populates="target_links")
    source_circuit = relationship("Circuit", foreign_keys=[source_circuit_id])
    target_circuit = relationship("Circuit", foreign_keys=[target_circuit_id])
