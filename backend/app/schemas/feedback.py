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


class FeedbackResponse(BaseModel):
    saved: int
    next_round_id: Optional[uuid.UUID] = None
    next_round_number: Optional[int] = None
    monitoring_activated: bool = False
    message: str
