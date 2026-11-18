"""数据库整库备份运行台账（系统级）。

每次备份（自动/手动）写一行，记录备份结果与（可选的）自动校验结果，供页面回溯对账。
刻意不挂 TenantMixin：整库 pg_dump 是跨租户的全局操作，这是运维台账而非租户业务数据，
因此不受 ORM 租户过滤影响（do_orm_execute / before_flush 只作用于 TenantMixin 子类）。
"""
from sqlalchemy import BigInteger, Column, Integer, JSON, String, Text
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime


class DbBackupRun(Base):
    __tablename__ = "db_backup_runs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(UTCDateTime, server_default=func.now(), index=True)

    trigger = Column(String(10), nullable=False)        # auto | manual
    status = Column(String(10), nullable=False)         # success | failed
    operator = Column(String(50), nullable=True)        # 手动=用户名；自动=system

    filename = Column(String(255), nullable=True)       # 产出的 dump 文件名（失败可能为空）
    size_bytes = Column(BigInteger, nullable=True)
    duration_ms = Column(Integer, nullable=True)        # pg_dump 耗时
    error = Column(Text, nullable=True)                 # 备份失败原因
    retention_deleted = Column(Integer, nullable=True)  # 本次清理掉的过期 auto 文件数

    # 自动校验结果：passed | failed | error | skipped（未开启自动校验）；手动一般为 skipped/null
    verify_status = Column(String(10), nullable=True)
    verify_error = Column(Text, nullable=True)
    verify_checks = Column(JSON, nullable=True)         # 各表行数快照 [{table, count}]
