"""文档分类 (4桶) Pydantic schemas"""
from pydantic import BaseModel, field_validator
from typing import Optional, List
import uuid
from datetime import datetime


VALID_BUCKETS = ("very_relevant", "relevant", "uncertain", "irrelevant")


class ClassifyRequest(BaseModel):
    bucket: str
    reason: Optional[str] = None

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, v):
        if v not in VALID_BUCKETS:
            raise ValueError(f"bucket must be one of {VALID_BUCKETS}")
        return v


class MoveRequest(BaseModel):
    to_bucket: str

    @field_validator("to_bucket")
    @classmethod
    def validate_bucket(cls, v):
        if v not in VALID_BUCKETS:
            raise ValueError(f"to_bucket must be one of {VALID_BUCKETS}")
        return v


class ClassificationOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    bucket: str
    classified_at: datetime
    moved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BucketDocumentOut(BaseModel):
    document_id: uuid.UUID
    title: str
    one_line_summary: Optional[str] = None
    source: str
    agent_score: Optional[float] = None
    classified_at: datetime
    bucket: str


class BucketSummary(BaseModel):
    very_relevant: List[BucketDocumentOut] = []
    relevant: List[BucketDocumentOut] = []
    uncertain: List[BucketDocumentOut] = []
    irrelevant: List[BucketDocumentOut] = []
    counts: dict  # {"very_relevant": 3, "relevant": 5, ...}
