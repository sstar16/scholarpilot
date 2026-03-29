import uuid
from datetime import datetime, timezone
from sqlalchemy import Integer, Text, DateTime, ForeignKey, JSON, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("relevance IN (-1, 0, 1, 2)", name="ck_feedback_relevance"),
        UniqueConstraint("user_id", "document_id", "round_id", name="uq_user_doc_round"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("search_rounds.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)

    # 核心反馈信号
    relevance: Mapped[int] = mapped_column(Integer, nullable=False)
    # -1=无关 / 0=不确定 / 1=相关 / 2=非常相关
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM 从 reason 中提取的结构化信号
    positive_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    negative_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    round: Mapped["SearchRound"] = relationship("SearchRound", back_populates="feedbacks")
    document: Mapped["Document"] = relationship("Document", back_populates="feedbacks")
