"""异地备份同步运行台账（系统级）。

每次异地同步（自动/手动）写一行，记录同步结果，供页面回溯对账与失败排查。
刻意不挂 TenantMixin：异地同步是把整库 dump 目录推到远端，是跨租户的全局运维操作，
属于运维台账而非租户业务数据，因此不受 ORM 租户过滤影响。
仿 db_backup_run：仅保留最近 N 条（见 offsite_sync_service.prune_runs）。
"""
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime


class OffsiteSyncRun(Base):
    __tablename__ = "offsite_sync_runs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(UTCDateTime, server_default=func.now(), index=True)

    trigger = Column(String(10), nullable=False)        # auto | manual
    status = Column(String(10), nullable=False)         # success | failed
    operator = Column(String(50), nullable=True)        # 手动=用户名；自动=system

    target_type = Column(String(20), nullable=True)     # rclone | rsync | sftp
    source_dir = Column(String(500), nullable=True)     # 本次同步的源目录
    duration_ms = Column(Integer, nullable=True)        # 同步耗时
    message = Column(String(200), nullable=True)        # 结果简述（成功消息等）
    error = Column(Text, nullable=True)                 # 失败原因（已截断脱敏）
