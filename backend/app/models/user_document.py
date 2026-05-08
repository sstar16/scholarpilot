"""UserDocument: per-user-per-document-per-project ownership 表。

设计动机（spec docs/spec-pdf-ownership-sync.md）:
- 当前 Document 表是全局共享的 — backend 无法回答"用户 X 在 project P 下过哪些 doc"
- 多设备同步需要：A 设备下载 → backend 记 ownership → B 设备登录后能拉 list 静默批量下

source 字段语义:
- 'downloaded' — 用户从 backend 触发 fetcher 抓原文后拿 binary
- 'uploaded_local' — 用户从本机选 PDF 上传，**不**送 backend（隐私 + 流量）
- 'uploaded_synced' — 用户从本机选 PDF 上传 + 主动选了"同步到云端"，binary 也存 backend
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
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

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
