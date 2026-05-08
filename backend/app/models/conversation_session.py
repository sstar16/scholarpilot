import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)

    # 状态机
    current_state: Mapped[str] = mapped_column(String(50), default="idle")
    # idle | intent_analysis | intent_confirmation | search_mode_selection
    # keyword_confirmation | searching | scoring | classification
    # investigation | round_finalize | exit_decision | monitoring_config

    # JSONB: 当前 envelope、auto_confirm flags、agent 中间结果等
    state_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    # 对话消息 [{role, content, timestamp, metadata}]
    messages: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

    # 检索模式: static_db | api | hybrid
    search_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User")
    project: Mapped["Project"] = relationship("Project")
