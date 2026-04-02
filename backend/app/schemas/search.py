from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime


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

    class Config:
        from_attributes = True


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
    url: Optional[str]
    doi: Optional[str]
    journal: Optional[str]
    citation_count: int
    pdf_url: Optional[str]
    ai_summary: Optional[str]
    ai_key_points: Optional[List[str]]
    ai_relevance_reason: Optional[str]
    ai_summary_source: str
    quality_score: Optional[float]
    # 本轮打分
    rank_in_round: Optional[int] = None
    initial_score: Optional[float] = None
    # Scoring Agent 评分
    agent_score: Optional[float] = None       # 0-10 LLM 评分
    agent_rationale: Optional[str] = None     # 评分理由
    one_line_summary: Optional[str] = None    # 一句话总结
    below_cutoff: bool = False                # 是否在斩杀线以下
    # 反馈状态
    user_feedback: Optional[int] = None  # -1/0/1/2 或 None

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
