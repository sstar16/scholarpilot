from pydantic import BaseModel
from typing import Optional, List
import uuid


class ImportPdfResponse(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    status: str  # always "parsing" on success


class ImportConfirmRequest(BaseModel):
    title: str
    title_zh: Optional[str] = None
    authors: List[str]
    year: Optional[int] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    journal: Optional[str] = None
    one_line_summary: str
    concept_tags: List[str]


class ImportConfirmResponse(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    next_status: str  # "scoring" or "ready"
