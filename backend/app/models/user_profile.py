import uuid
from datetime import datetime, timezone
from sqlalchemy import Integer, Text, DateTime, ForeignKey, UniqueConstraint, ARRAY, String, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_user_project_profile"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    # 关键词偏好（Phase 1 主要使用）
    preferred_keywords: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    excluded_keywords: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_sources: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_doc_types: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_authors: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)

    feedback_count: Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Memory Agent: LLM-driven structured memory (replaces keyword-only profile)
    memory_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_version: Mapped[int] = mapped_column(Integer, default=0)

    # Phase 3.2: Structured memory from bucket signals (machine-readable)
    structured_memory: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    # Phase 4 (Markdown memory): 用户可见可编辑的项目级 .md 文本
    # 记录"在这个项目里研究什么" —— 具体方向/子问题/关注的关键文献。
    # 与 user_memories.markdown_text（用户级）组合喂给 agents。
    project_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 项目食谱（auto_recipe_md）：每次 4 桶反馈完成后纯统计 regenerate，
    # 写入桶分布 / 来源命中率 / 关键词信号 / 主题簇 / 给 agent 的硬性指引。
    # 用户只读不可编辑（区别于 project_markdown），通过 build_combined_memory_for_agents
    # 拼到 agent prompt 里。
    auto_recipe_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipe_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    project: Mapped["Project"] = relationship("Project", back_populates="user_profile")
