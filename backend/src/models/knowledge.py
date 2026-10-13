from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Index
from sqlalchemy.sql import func

from ..database import Base


class KnowledgeArticle(Base):
    """知识库文章（运维经验沉淀：故障处理 / 配置手册 / 操作 SOP / FAQ）"""
    __tablename__ = "knowledge_articles"
    __table_args__ = (
        Index('ix_knowledge_articles_category', 'category'),
        Index('ix_knowledge_articles_created_at', 'created_at'),
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)
    category = Column(String(50), default="其他")  # 故障处理/配置手册/操作SOP/FAQ/其他
    tags = Column(String(200), default="")  # 逗号分隔标签
    summary = Column(String(500), default="")  # 摘要（列表展示）
    content = Column(Text, default="")  # Markdown 正文
    author = Column(String(50), default="")
    is_published = Column(Boolean, default=True)  # 草稿/发布
    view_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
