from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime
from ..tenant.mixin import TenantMixin

class Aggregate(TenantMixin, Base):
    __tablename__ = "aggregates"
    
    id = Column(Integer, primary_key=True, index=True)
    network = Column(String(50), nullable=False)  # CIDR格式
    name = Column(String(100))
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
