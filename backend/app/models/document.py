import uuid
from datetime import datetime, timezone, date
from sqlalchemy import String, Text, Float, DateTime, Date, JSON, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 数据源标识
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # paper | patent | preprint | news | conference

    # 核心字段
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_zh: Mapped[str | None] = mapped_column(Text, nullable=True)  # 中文翻译（全球模式）
    authors: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    journal: Mapped[str | None] = mapped_column(String(300), nullable=True)
    citation_count: Mapped[int] = mapped_column(default=0)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── 全文状态（双格式共存：PDF 和 HTML 互相独立）─────────────────
    # 聚合状态：任一格式 available → available；用于前端"有没有全文"判断
    fulltext_status: Mapped[str] = mapped_column(String(30), default="not_attempted")
    # not_attempted | downloading | available | failed
    # 兼容字段：指向主文件（优先 PDF，fallback HTML），保留给老代码读
    fulltext_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # PDF 格式独立状态 + 路径
    fulltext_pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fulltext_pdf_status: Mapped[str] = mapped_column(String(30), default="not_attempted")
    # HTML 格式独立状态 + 路径（可以和 PDF 共存）
    fulltext_html_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fulltext_html_status: Mapped[str] = mapped_column(String(30), default="not_attempted")

    fulltext_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # ≤150,000 字符（2026-05-03 从 50k 提到 150k；ProbeAgent 按 IMRaD 切段，要全文不要采样）

    # AI 生成内容（核心差异化）
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_points: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    ai_relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary_source: Mapped[str] = mapped_column(String(30), default="not_generated")
    # not_generated | from_abstract | from_fulltext | from_title

    # 用户手动覆盖版本（展示时优先 _user，缺省用 AI 版）
    # AI 重跑只写非 _user 字段，用户手工编辑永不被覆盖
    ai_summary_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_points_user: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)

    # 国家代码（ISO-2），如 ["CN", "US"]
    countries: Mapped[list | None] = mapped_column(ARRAY(String(5)), nullable=True)

    # 质量评分
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Scoring Agent 一句话总结（跨轮保留的规范版本）
    one_line_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 用户覆盖版；卡片展示优先 _user
    one_line_summary_user: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM 抽取的核心概念 (仅 name 去重列表,完整 confidence/type 在 .md frontmatter)
    concept_tags: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)

    # 探针缓存：跨提问/跨会话复用的 section 级原文抽取结果
    # Schema: [{question_hint, question_concepts, excerpts, adopted, source, created_at}]
    # adopted=True 的条目会被写入 .md 的结构化抽取 section
    probe_cache: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # 去重
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # ── 导入来源（M2：manual_upload 表示用户手动上传 PDF，不走检索轮次）─
    import_source: Mapped[str] = mapped_column(String(30), default="search", index=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    round_documents: Mapped[list["RoundDocument"]] = relationship("RoundDocument", back_populates="document")
    feedbacks: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="document")

    # ── 用户覆盖合并器：优先用 _user 版，缺省回 AI 版。仅在 Python 侧生效。
    @property
    def effective_one_line_summary(self) -> str | None:
        return self.one_line_summary_user or self.one_line_summary

    @property
    def effective_ai_summary(self) -> str | None:
        return self.ai_summary_user or self.ai_summary

    @property
    def effective_ai_key_points(self) -> list | None:
        if self.ai_key_points_user is not None:
            return self.ai_key_points_user
        return self.ai_key_points

    @property
    def user_edited_fields(self) -> list[str]:
        edited: list[str] = []
        if self.one_line_summary_user is not None:
            edited.append("one_line_summary")
        if self.ai_key_points_user is not None:
            edited.append("ai_key_points")
        if self.ai_summary_user is not None:
            edited.append("ai_summary")
        return edited
