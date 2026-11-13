from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime
from ..tenant.mixin import TenantMixin

class VlanGroup(TenantMixin, Base):
    """VLAN组/域，如「上海办公网」"""
    __tablename__ = "vlan_groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 组名
    site_id = Column(Integer, ForeignKey("sites.id"))  # 关联站点（可为空，表示全局）
    description = Column(String(500))
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())

class Vlan(TenantMixin, Base):
    """VLAN记录"""
    __tablename__ = "vlans"
    
    id = Column(Integer, primary_key=True, index=True)
    vid = Column(Integer, nullable=False)  # VLAN ID，1-4094
    name = Column(String(100))  # 如「办公网」「管理网」「DMZ」
    group_id = Column(Integer, ForeignKey("vlan_groups.id"))  # 关联VlanGroup
    site_id = Column(Integer, ForeignKey("sites.id"))  # 关联站点（可为空，表示全局）
    status = Column(String(20), default="active")  # active / reserved / deprecated
    description = Column(String(500))
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
