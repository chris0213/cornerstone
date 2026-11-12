from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from ..database import Base, UTCDateTime

class SystemConfig(Base):
    """系统配置"""
    __tablename__ = "system_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)  # 配置键
    value = Column(Text)  # 配置值（JSON格式）
    description = Column(String(255))  # 配置说明
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
