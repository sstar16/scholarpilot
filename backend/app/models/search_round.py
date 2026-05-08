import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, UniqueConstraint, ARRAY, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class SearchRound(Base):
    __tablename__ = "search_rounds"
    __table_args__ = (UniqueConstraint("project_id", "round_number", name="uq_project_round"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # 状态机
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending | awaiting_keywords | searching | scoring | saving | summarizing
    # | awaiting_feedback | complete | partial_complete | failed
    # | cancelled | closed | closed_no_feedback

    # 本轮配置
    time_horizon_years: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 5/10/20/None=全时间
    max_results: Mapped[int] = mapped_column(Integer, default=10)
    language_scope: Mapped[str] = mapped_column(String(20), default="chinese")  # chinese|global
    sources_used: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    search_queries: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 各数据源实际查询词

    # 结果统计
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, default=0)
    source_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 各数据源返回统计

    # 进度（供前端轮询）
    progress: Mapped[float] = mapped_column(default=0.0)
    progress_message: Mapped[str] = mapped_column(String(200), default="")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Answer Now (partial complete) ——
    # 用户中途点"先看现有结果"时, worker 在 stage 边界用已有部分文献调 LLM 合成
    # best-effort 答案, 状态转为 partial_complete (新终态值, 不进 awaiting_feedback).
    partial_answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    partial_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # M2: 7 天 TTL — finalize 时设为 NOW + 7d；cleanup_expired_round_cache 每日 03:30 删过期
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project: Mapped["Project"] = relationship("Project", back_populates="search_rounds")
    round_documents: Mapped[list["RoundDocument"]] = relationship("RoundDocument", back_populates="round", cascade="all, delete-orphan", order_by="RoundDocument.rank_in_round")
    feedbacks: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="round", cascade="all, delete-orphan")
