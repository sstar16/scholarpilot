from pydantic import BaseModel, Field
from typing import Literal, Optional


class BYOKTestRequest(BaseModel):
    provider: Literal["openai", "anthropic", "deepseek", "moonshot", "custom"]
    api_key: str = Field(..., min_length=1, max_length=512)
    model: Optional[str] = Field(None, max_length=128)
    base_url: Optional[str] = Field(None, max_length=256)


class BYOKTestResponse(BaseModel):
    ok: bool
    sample_response: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None  # 简短分类，不含 key 或 raw exception text
