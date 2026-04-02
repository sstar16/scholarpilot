import uuid
from datetime import datetime, timezone
from sqlalchemy import Integer, Text, DateTime, ForeignKey, UniqueConstraint, ARRAY, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_user_project_profile"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    # 关键词偏好（Phase 1 主要使用）
    preferred_keywords: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    excluded_keywords: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_sources: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_doc_types: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_authors: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)

    feedback_count: Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Memory Agent: LLM-driven structured memory (replaces keyword-only profile)
    memory_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_version: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped["Project"] = relationship("Project", back_populates="user_profile")

    # Phase 2: embedding 向量（pgvector）
    if HAS_PGVECTOR:
        positive_embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
        negative_embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
