"""UserMemory — 用户级 Markdown 记忆（跨项目共享的身份/通用偏好）。

与 UserProfile（项目级）区别：
- UserMemory: (user_id UNIQUE) 一对一，记用户的"谁"——昵称/职业/研究大方向/偏好
- UserProfile.project_markdown: (user_id, project_id) 一对一，记"在此项目里研究什么"

两层组合喂给 QueryPlanAgent/ScoringAgent，避免跨项目污染。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class UserMemory(Base):
    __tablename__ = "user_memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    markdown_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
