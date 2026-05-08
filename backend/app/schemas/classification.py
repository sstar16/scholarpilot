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
    # Fulltext 状态（2026-05-03 补全）：之前漏返导致用户从文献库进 FulltextViewer
    # 时所有 status 字段都 undefined，组件 fallback 到 'not_attempted' 显示"未下载"
    # 空态 — 哪怕 backend 磁盘上 PDF 实际存在也看不到。不返 fulltext_text 字段（太大，
    # 列表场景用不到，只在 FulltextViewer 拉单文献详情时取）。
    fulltext_status: Optional[str] = None
    fulltext_pdf_status: Optional[str] = None
    fulltext_pdf_path: Optional[str] = None
    fulltext_html_status: Optional[str] = None
    fulltext_html_path: Optional[str] = None
    fulltext_path: Optional[str] = None  # 旧字段，PDF/HTML 共用，向后兼容
    pdf_url: Optional[str] = None  # canDownloadPdf 预检需要
    doi: Optional[str] = None      # 同上
    url: Optional[str] = None      # canDownloadHtml 预检需要
    external_id: Optional[str] = None  # patenthub 走付费源时需要


class BucketSummary(BaseModel):
    very_relevant: List[BucketDocumentOut] = []
    relevant: List[BucketDocumentOut] = []
    uncertain: List[BucketDocumentOut] = []
    irrelevant: List[BucketDocumentOut] = []
    counts: dict  # {"very_relevant": 3, "relevant": 5, ...}
