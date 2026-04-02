"""
文档分类模型 — 4桶系统
每个用户在每个项目中对每篇文档只有一个分类（跨轮次持久化）
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


BUCKET_VALUES = ("very_relevant", "relevant", "uncertain", "irrelevant")


class DocumentClassification(Base):
    __tablename__ = "document_classifications"
    __table_args__ = (
        UniqueConstraint("user_id", "document_id", "project_id", name="uq_user_doc_project_class"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)

    # 桶分类: very_relevant | relevant | uncertain | irrelevant
    bucket: Mapped[str] = mapped_column(String(20), nullable=False)

    # 在哪一轮首次分类的（可为空，如来自监控结果）
    classified_in_round_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("search_rounds.id", ondelete="SET NULL"), nullable=True
    )

    # 用户评价原因
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM 提取的结构化信号
    positive_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    negative_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)

    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    moved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    document: Mapped["Document"] = relationship("Document")
    project: Mapped["Project"] = relationship("Project")
