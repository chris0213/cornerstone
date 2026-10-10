from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.sql import func

from ..database import Base

class Backup(Base):
    __tablename__ = "backups"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    version = Column(Integer, default=1)  # 版本号，同设备自增
    content = Column(Text)  # 配置内容（小配置直接存DB）
    content_hash = Column(String(64))  # SHA256哈希，用于快速判断是否变更
    file_path = Column(String(255))  # 文件路径（大配置存文件）
    trigger = Column(String(20))  # manual / scheduled / pre_change
    operator = Column(String(50))
    status = Column(String(20), default="pending")  # pending, success, failed
    error_message = Column(String(500))  # 失败原因
    has_change = Column(Boolean, default=False)  # 与上一版本相比是否有变更
    change_summary = Column(String(200))  # 变更摘要
    tag = Column(String(100))  # 人工标签
    duration_ms = Column(Integer)  # 采集耗时
    size = Column(Float)  # bytes
    note = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)