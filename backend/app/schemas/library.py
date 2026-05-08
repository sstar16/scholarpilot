"""Pydantic schemas for the Literature Library API."""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LibraryFileSummary(BaseModel):
    """单篇文献的列表卡片数据。"""
    model_config = ConfigDict(extra="ignore")

    slug: str
    title: str
    title_zh: Optional[str] = None
    authors_short: str = ""
    year: Optional[int] = None
    bucket: Optional[str] = None
    quality_score: Optional[float] = None
    updated_at: Optional[str] = None
    extract_status: Optional[str] = None
    # 扩展字段（P1 Library 卡片操作）：原文链接 / DOI / PDF / 文档 ID
    document_id: Optional[str] = None
    source: Optional[str] = None
    external_id: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None


class LibraryListResponse(BaseModel):
    total: int
    by_bucket: dict[str, int]
    files: list[LibraryFileSummary]


class LibraryDetailResponse(BaseModel):
    slug: str
    frontmatter: dict[str, Any]
    body_md: str
    raw: str


class LibraryRebuildResponse(BaseModel):
    status: str
    task_id: Optional[str] = None


class LibraryDeleteBatchRequest(BaseModel):
    """批量从项目移除文献（仅移除项目关联，保留 global Document）。"""
    slugs: list[str]


class LibraryDeleteBatchResponse(BaseModel):
    deleted: int
    failed: list[str] = []
    remaining_total: int
