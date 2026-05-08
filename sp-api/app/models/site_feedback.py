"""SiteFeedback — 首页反馈按钮提交的用户产品反馈（bug / 建议 / 其他）。

sp-api 版（原 backend.user_feedback 表，改名以避免与项目反馈语义混淆）。
表名仍叫 user_feedback 是为了沿用历史 schema；类名升级到 SiteFeedback。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteFeedback(Base):
    __tablename__ = "site_feedback"
    __table_args__ = (
        CheckConstraint(
            "category IN ('bug', 'suggestion', 'praise', 'other')",
            name="ck_site_feedback_category",
        ),
        CheckConstraint(
            "status IN ('open', 'triaged', 'resolved', 'wontfix')",
            name="ck_site_feedback_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # 允许匿名（未登录场景），登录则外键关联
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_email_snapshot: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
    )

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
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
