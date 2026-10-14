import sqlalchemy as sa
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func

from ..database import Base

class Prefix(Base):
    __tablename__ = "prefixes"
    
    id = Column(Integer, primary_key=True, index=True)
    aggregate_id = Column(Integer, ForeignKey("aggregates.id"))
    network = Column(String(50), nullable=False)  # CIDR格式
    site_id = Column(Integer, ForeignKey("sites.id"))
    vlan = Column(String(20))
    usage = Column(String(100))
    custom_scan_ports = Column(String(200), nullable=True, comment="自定义TCP扫描端口组，逗号分隔；空则用默认")
    auto_scan_enabled = Column(Boolean, nullable=False, server_default=sa.false(), comment="是否启用自动定时扫描")
    scan_cron = Column(String(50), nullable=False, server_default="0 */6 * * *", comment="自动扫描cron表达式")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
