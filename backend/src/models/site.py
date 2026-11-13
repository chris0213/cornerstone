from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime
from ..tenant.mixin import TenantMixin

class Site(TenantMixin, Base):
    __tablename__ = "sites"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    location = Column(String(255))
    city = Column(String(50))
    room = Column(String(50))
    contact = Column(String(100))
    contact_phone = Column(String(20))
    status = Column(String(20), default="online")  # online, alert, offline
    alert_count = Column(Integer, default=0)
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
