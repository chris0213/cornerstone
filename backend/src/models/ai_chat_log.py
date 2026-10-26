from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from ..database import Base


class AIChatLog(Base):
    """AI 运维助手聊天日志

    仅记录「用户提问 + AI 回答（已脱敏）」，不存储底层查询返回的明细行，
    避免设备 SN、负责人、专线资费、审计操作人/IP 等 PII 落入日志表。
    访问受控：本人仅可见自己的记录，超级管理员可见全部。保留 30 天。
    """
    __tablename__ = "ai_chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    question = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False, default="")
    data_type = Column(String(50), nullable=True, index=True)
    client_ip = Column(String(50), nullable=True)
    # 调用元数据（可空，兼容历史记录）：模型名、耗时毫秒、结果状态与失败原因
    model = Column(String(100), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    status = Column(String(20), nullable=True)  # success / failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User")
