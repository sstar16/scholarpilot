import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class MonitorJob(Base):
    __tablename__ = "monitor_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    schedule: Mapped[str] = mapped_column(String(20), default="daily")  # daily | weekly
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    search_config: Mapped[dict] = mapped_column(JSON, nullable=False)  # 从最终轮次状态导出
    # Phase 3.4: Push config
    novelty_threshold: Mapped[float] = mapped_column(default=0.6)
    push_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    pending_push_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project: Mapped["Project"] = relationship("Project", back_populates="monitor_job")
    results: Mapped[list["MonitorResult"]] = relationship("MonitorResult", back_populates="job", cascade="all, delete-orphan")


class MonitorResult(Base):
    __tablename__ = "monitor_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("monitor_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    new_docs_found: Mapped[int] = mapped_column(Integer, default=0)
    docs: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{document_id, score, summary}]
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["MonitorJob"] = relationship("MonitorJob", back_populates="results")
