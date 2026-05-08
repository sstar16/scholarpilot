from pydantic import BaseModel, field_validator
from typing import Optional, List
import uuid
from datetime import datetime, date


class RoundStatusOut(BaseModel):
    id: uuid.UUID
    round_number: int
    status: str
    progress: float
    progress_message: str
    time_horizon_years: Optional[int]
    max_results: int
    language_scope: str
    total_candidates: int
    selected_count: int
    source_stats: Optional[dict] = None
    search_queries: Optional[dict] = None
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    # Answer Now —— partial 答案落 DB 后, 前端拉 status 也能看到
    partial_answer: Optional[dict] = None
    partial_completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PartialAnswerOut(BaseModel):
    """Answer Now: best-effort 部分答案的结构化输出."""
    answer_markdown: str
    doc_ids_cited: List[str] = []
    partial: bool = True
    interrupted_at_stage: str
    doc_count_used: int = 0
    confidence: float = 0.0
    disclaimer: str = ""
    # 仅在 LLM 失败时填充, 让前端可显示降级提示
    error: Optional[str] = None


class AnswerNowAcceptedOut(BaseModel):
    """触发 Answer Now 的 202 响应."""
    accepted: bool
    current_stage: str
    message: str


class DocumentOut(BaseModel):
    id: uuid.UUID
    source: str
    external_id: str
    doc_type: str
    title: str
    title_zh: Optional[str]
    authors: Optional[str]
    abstract: Optional[str]
    publication_date: Optional[str]

    @field_validator("publication_date", mode="before")
    @classmethod
    def _coerce_pub_date(cls, v):
        # ORM 字段是 date/datetime；前端协议要 string → 容忍两种输入
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return v
    url: Optional[str]
    doi: Optional[str]
    journal: Optional[str]
    citation_count: int
    pdf_url: Optional[str]
    ai_summary: Optional[str]
    ai_key_points: Optional[List[str]]
    ai_relevance_reason: Optional[str]
    ai_summary_source: str
    concept_tags: Optional[List[str]] = None
    quality_score: Optional[float]
    countries: Optional[List[str]] = None
    # 本轮打分
    rank_in_round: Optional[int] = None
    initial_score: Optional[float] = None
    # Scoring Agent 评分
    agent_score: Optional[float] = None       # 0-10 LLM 评分
    agent_rationale: Optional[str] = None     # 评分理由
    one_line_summary: Optional[str] = None    # 一句话总结
    below_cutoff: bool = False                # 是否在斩杀线以下
    # 反馈状态
    user_feedback: Optional[int] = None  # -1/0/1/2 或 None (legacy)
    # 桶分类
    bucket: Optional[str] = None  # very_relevant/relevant/uncertain/irrelevant
    # 全文下载状态（聚合 + 兼容字段）
    fulltext_status: Optional[str] = None  # not_attempted / downloading / available / failed
    fulltext_path: Optional[str] = None    # 兼容：指向主文件（优先 PDF）
    # 双格式独立状态 —— PDF 和 HTML 可以共存，用户可分别触发下载
    fulltext_pdf_status: Optional[str] = None
    fulltext_pdf_path: Optional[str] = None
    fulltext_html_status: Optional[str] = None
    fulltext_html_path: Optional[str] = None

    class Config:
        from_attributes = True


class RoundResultsOut(BaseModel):
    round_id: uuid.UUID
    round_number: int
    status: str
    documents: List[DocumentOut]
    total_candidates: int
    source_stats: Optional[dict] = None
    search_queries: Optional[dict] = None
