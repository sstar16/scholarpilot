import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)  # 研究方向描述
    domain: Mapped[str] = mapped_column(String(100), nullable=False)  # biology/chemistry/cs/economics/...
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|monitoring|archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User", back_populates="projects")
    search_rounds: Mapped[list["SearchRound"]] = relationship("SearchRound", back_populates="project", cascade="all, delete-orphan", order_by="SearchRound.round_number")
    user_profile: Mapped["UserProfile"] = relationship("UserProfile", back_populates="project", uselist=False, cascade="all, delete-orphan")
    monitor_job: Mapped["MonitorJob"] = relationship("MonitorJob", back_populates="project", uselist=False, cascade="all, delete-orphan")
