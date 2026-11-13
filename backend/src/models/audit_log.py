from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime
from ..tenant.mixin import TenantMixin

class AuditLog(TenantMixin, Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    resource = Column(String(100))
    detail = Column(Text)
    ip_address = Column(String(50))
    success = Column(String(10), default="true")
    created_at = Column(UTCDateTime, server_default=func.now(), index=True)
