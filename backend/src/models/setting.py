from sqlalchemy import Column, Integer, String, Text
from ..database import Base
from ..tenant.mixin import TenantMixin

class Setting(TenantMixin, Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True)
    value = Column(Text)
