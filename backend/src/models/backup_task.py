from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime

class BackupTask(Base):
    __tablename__ = "backup_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 任务名称
    
    __table_args__ = (
        UniqueConstraint('name', name='uq_backup_task_name'),
    )
    is_enabled = Column(Boolean, default=True)  # 是否启用
    cron_expr = Column(String(50))  # Cron表达式
    device_ids = Column(String(500))  # JSON数组，如 "[1,2,3]"
    site_id = Column(Integer, ForeignKey("sites.id"))  # 按站点批量
    credential_id = Column(Integer, ForeignKey("credentials.id"))  # 使用哪套凭证
    vendor = Column(String(50))  # 厂商类型，用于指定备份命令
    retention_count = Column(Integer, default=30)  # 保留最近N个版本
    retention_days = Column(Integer, default=90)  # 保留最近N天
    notify_on_change = Column(Boolean, default=True)  # 配置变更时是否告警
    notify_on_fail = Column(Boolean, default=True)  # 备份失败时是否告警
    last_run_at = Column(UTCDateTime)
    last_run_status = Column(String(20))  # success / partial_fail / failed
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())
