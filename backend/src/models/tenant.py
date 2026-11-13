"""租户模型。"""
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime, JSONType


class Tenant(Base):
    """租户（平台级实体，本身不参与行级过滤）。"""

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)   # 短码，后续用于登录/URL/文件目录
    name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active")  # active/suspended/trial/archived
    plan = Column(String(50), nullable=False, default="standard", server_default="standard")
    contact_name = Column(String(50))
    contact_email = Column(String(100))
    quota = Column(JSONType)                                             # 配额（站点/设备/用户/存储）
    description = Column(Text)
    expires_at = Column(UTCDateTime)
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
    deleted_at = Column(UTCDateTime)                                     # 软删，禁止物理删除租户
