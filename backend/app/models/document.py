import uuid
from datetime import datetime, timezone, date
from sqlalchemy import String, Text, Float, DateTime, Date, JSON, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 数据源标识
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # paper | patent | preprint | news | conference

    # 核心字段
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_zh: Mapped[str | None] = mapped_column(Text, nullable=True)  # 中文翻译（全球模式）
    authors: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    journal: Mapped[str | None] = mapped_column(String(300), nullable=True)
    citation_count: Mapped[int] = mapped_column(default=0)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 全文状态
    fulltext_status: Mapped[str] = mapped_column(String(30), default="not_attempted")
    # not_attempted | downloading | available | failed
    fulltext_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fulltext_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # ≤50,000 字符

    # AI 生成内容（核心差异化）
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_points: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    ai_relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary_source: Mapped[str] = mapped_column(String(30), default="not_generated")
    # not_generated | from_abstract | from_fulltext

    # 质量评分
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Scoring Agent 一句话总结（跨轮保留的规范版本）
    one_line_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 去重
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    round_documents: Mapped[list["RoundDocument"]] = relationship("RoundDocument", back_populates="document")
    feedbacks: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="document")

    # pgvector embedding（若 pgvector 不可用则跳过）
    if HAS_PGVECTOR:
        embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
