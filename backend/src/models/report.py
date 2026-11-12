from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from ..database import Base, UTCDateTime


class MonthlyReport(Base):
    """月报生成记录"""
    __tablename__ = "monthly_reports"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, default=0)  # 字节
    status = Column(String(20), default="done")  # generating / done / failed
    error_message = Column(Text, default="")
    generated_by = Column(String(100), default="")
    generated_at = Column(UTCDateTime, server_default=func.now())
