"""
Per-Source Keyword Schemas
用于 prepare / confirm-keywords 端点的请求/响应模型
"""
from pydantic import BaseModel
from typing import List, Optional
import uuid


class SourceKeywordPlanOut(BaseModel):
    source_id: str
    display_name: str
    query: str
    query_format: str
    language: str
    enabled: bool
    generation_method: str
    notes: str
    category: str = "literature"


class KeywordGenerationResponse(BaseModel):
    round_id: uuid.UUID
    round_number: int
    base_query: str
    original_chinese_query: Optional[str] = None
    english_query_source: str = "regex"
    cn_query_source: str = "none"
    source_plans: List[SourceKeywordPlanOut]
    generation_time_ms: int


class SourceKeywordConfirmation(BaseModel):
    source_id: str
    query: str
    enabled: bool


class KeywordConfirmRequest(BaseModel):
    source_plans: List[SourceKeywordConfirmation]
