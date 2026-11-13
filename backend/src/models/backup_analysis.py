from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime
from ..tenant.mixin import TenantMixin


class BackupAnalysis(TenantMixin, Base):
    """备份变更 AI 分析结果"""
    __tablename__ = "backup_analyses"

    id = Column(Integer, primary_key=True, index=True)
    backup_id = Column(Integer, ForeignKey("backups.id"), unique=True, nullable=False)
    summary = Column(String(500), nullable=False)          # 一句话总结
    changes_json = Column(Text, default="[]")              # JSON 数组，变更详情
    risk_level = Column(String(20), default="low")         # low / medium / high
    risk_detail = Column(String(500), default="")           # 风险说明
    total_added = Column(Integer, default=0)
    total_removed = Column(Integer, default=0)
    model_used = Column(String(100), default="")            # 使用的模型名称
    created_at = Column(UTCDateTime, server_default=func.now())
