"""DevLog — 后端日志归档表（ringbuffer + DB flush）。

sp-api 版差异：round_id / project_id 仍是 UUID 但**不再加 FK**（sp-api 无 projects/search_rounds 表）；
客户端把 client_run_id / client_project_id 当作 UUID 直接写进来。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, String, Text, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class DevLog(Base):
    __tablename__ = "dev_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    round_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
