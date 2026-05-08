from pydantic import BaseModel, field_validator
from typing import Optional, List
import uuid


class FeedbackItem(BaseModel):
    document_id: uuid.UUID
    relevance: int  # -1 无关 / 0 不确定 / 1 相关 / 2 非常相关
    reason: Optional[str] = None

    @field_validator("relevance")
    @classmethod
    def validate_relevance(cls, v):
        if v not in (-1, 0, 1, 2):
            raise ValueError("relevance must be -1, 0, 1, or 2")
        return v


class FeedbackSubmit(BaseModel):
    feedbacks: List[FeedbackItem]


class MemoryFileOut(BaseModel):
    """单个 memory 文件 —— 客户端拿去写 <AppData>/scholarpilot/projects/<id>/memory/<filename>."""
    filename: str
    type: str           # identity / preference / reference / note
    name: str
    description: str
    body: str


class MemoryUpdateOut(BaseModel):
    """memory_agent 输出，附在 FeedbackResponse 里给客户端写本地多文件 + MEMORY.md 索引。"""
    version: int
    index_md: str
    files: List[MemoryFileOut]
    focus: str = ""


class FeedbackResponse(BaseModel):
    saved: int
    next_round_id: Optional[uuid.UUID] = None
    next_round_number: Optional[int] = None
    monitoring_activated: bool = False
    message: str
    memory_update: Optional[MemoryUpdateOut] = None
