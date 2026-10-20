from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from ..database import Base

class Credential(Base):
    __tablename__ = "credentials"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 凭证名称，如「华为核心设备组」
    
    __table_args__ = (
        UniqueConstraint('name', name='uq_credential_name'),
    )
    device_id = Column(Integer, ForeignKey("devices.id"))  # 关联设备（可为空）
    protocol = Column(String(20), default="ssh")  # ssh / telnet
    port = Column(Integer, default=22)
    username = Column(String(50), nullable=False)
    password = Column(String(500))  # 加密存储
    enable_password = Column(String(500))  # enable密码，加密存储
    auth_type = Column(String(20), default="password")  # password / key
    private_key = Column(String(2000))  # SSH私钥内容，加密存储
    jump_host = Column(String(50))  # 跳板机IP
    jump_port = Column(Integer, default=22)  # 跳板机端口
    jump_username = Column(String(50))  # 跳板机用户名
    jump_password = Column(String(500))  # 跳板机密码，加密存储
    description = Column(String(500))
    last_tested_at = Column(DateTime(timezone=True))  # 最近一次测试连接时间（UTC）
    last_test_status = Column(String(20))  # success / failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())