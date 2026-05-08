"""
Per-Source Keyword Schemas + QueryPlan 确认
用于 prepare / confirm-keywords 端点的请求/响应模型
"""
from pydantic import BaseModel
from typing import List, Optional
import uuid


class SourceKeywordPlanOut(BaseModel):
    source_id: str
    display_name: str
    query: str                   # primary = complex
    query_medium: str = ""
    query_simple: str = ""
    query_format: str
    language: str
    enabled: bool
    generation_method: str
    notes: str
    category: str = "literature"


class KeywordGenerationResponse(BaseModel):
    round_id: uuid.UUID
    round_number: int
    # QueryPlan 核心参数（用户可编辑）
    base_query: str
    original_chinese_query: Optional[str] = None
    exclude_terms: List[str] = []
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    max_per_source: int = 20
    language_scope: str = "international"
    plan_source: str = "agent"            # "agent" | "fallback"
    plan_rationale: str = ""              # Agent 策略说明
    # 旧字段保留兼容
    english_query_source: str = "regex"
    cn_query_source: str = "none"
    # Per-source 关键词方案
    source_plans: List[SourceKeywordPlanOut]
    generation_time_ms: int


class SourceKeywordConfirmation(BaseModel):
    source_id: str
    query: str
    query_medium: str = ""
    query_simple: str = ""
    enabled: bool


class KeywordConfirmRequest(BaseModel):
    source_plans: List[SourceKeywordConfirmation]
    # 用户编辑后的 QueryPlan 参数（可选，不传则用 Agent 原方案）
    base_query: Optional[str] = None
    original_chinese_query: Optional[str] = None
    exclude_terms: Optional[List[str]] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    max_per_source: Optional[int] = None
    language_scope: Optional[str] = None
    # Phase 3.0: 检索模式 — static_db | api | hybrid（默认 None=沿用现有行为）
    search_mode: Optional[str] = None
