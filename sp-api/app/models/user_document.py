"""UserDocument — sp-api 版（去掉 documents/projects FK，UUID 当客户端侧 ID 用）。

sp-api 没有 documents / projects 表；这里 document_id / project_id 是客户端侧 UUID（外部主键），
backend 仅做 ownership 记录 + binary 同步映射。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class UserDocument(Base):
    __tablename__ = "user_documents"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "document_id", "project_id", "format",
            name="uq_user_documents_user_doc_project_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # document_id / project_id 都是客户端侧 UUID（不绑 sp-api 表）
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'downloaded' | 'uploaded_local' | 'uploaded_synced'

    format: Mapped[str] = mapped_column(String(10), nullable=False)
    # 'pdf' | 'html'

    owned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
