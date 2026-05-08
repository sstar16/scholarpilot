"""
UserFeedback — 首页反馈按钮提交的用户产品反馈（bug / 建议 / 其他）。

与 app.models.feedback.Feedback 区分：
  - Feedback: 文献相关性 4 桶分类（per-document 领域反馈）
  - UserFeedback: 用户对产品本身的反馈（bug 报告、功能建议等）
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    __table_args__ = (
        CheckConstraint(
            "category IN ('bug', 'suggestion', 'praise', 'other')",
            name="ck_user_feedback_category",
        ),
        CheckConstraint(
            "status IN ('open', 'triaged', 'resolved', 'wontfix')",
            name="ck_user_feedback_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 允许匿名（未登录场景），登录则外键关联
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    user_email_snapshot: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
    )  # 冗余快照，用户被删也能看

    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    page_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
