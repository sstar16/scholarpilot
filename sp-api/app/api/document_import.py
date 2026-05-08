"""Document import endpoints — sp-api 简化版。

vs backend/app/api/document_import.py 改动：
- 删 ConversationSession / Document 依赖（sp-api 没有 documents / sessions 表）
- 删 inject_rich_message / project_scene / score_imported_document（无 LLM）
- 删 markitdown 多格式校验（sp-api 不装 markitdown，PDF 解析全在客户端）
- 仅保留：上传 PDF binary → 落盘 → 创建 DocumentImportJob 记录 → 返回 job_id
- 客户端拿到 job_id 后自己解析 + 写本地 DB；sp-api 仅做"二进制中转 + 跨设备同步"

路由：
  POST /api/projects/{project_id}/documents/import-pdf  上传 PDF（multipart/form-data）
  POST /api/documents/import-jobs/{job_id}/cancel       取消（删 tmp 文件）
  GET  /api/documents/import-jobs/{job_id}              查 job 状态
  GET  /api/documents/import-jobs/{job_id}/file         下载原始上传二进制
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_current_user_flexible
from app.models.document_import_job import DocumentImportJob
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["document-import"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MIN_UPLOAD_BYTES = 200

# sp-api 仅接受 PDF —— 多格式 (docx/pptx/...) 的解析由客户端 markitdown / pdf-extract 做
ALLOWED_EXTS = {".pdf"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",  # 兜底：扩展名合法就放行
    "",
}


def _get_tmp_dir() -> Path:
    base = os.environ.get("PDF_STORAGE_PATH", "/app/data/import_tmp")
    tmp = Path(base)
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


class ImportPdfResponse(BaseModel):
    job_id: uuid.UUID
    filename: str
    status: str  # always "uploaded" on success
    size: int


class ImportJobStatus(BaseModel):
    job_id: uuid.UUID
    project_id: uuid.UUID | None
    session_id: uuid.UUID | None
    user_id: uuid.UUID
    original_filename: str | None
    status: str
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


@router.post(
    "/projects/{project_id}/documents/import-pdf",
    response_model=ImportPdfResponse,
)
async def import_pdf(
    project_id: uuid.UUID,
    session_id: uuid.UUID | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传 PDF 二进制 → sp-api 落盘 → 创建 import job 记录。

    客户端轮询 /api/documents/import-jobs/{job_id} 拿 status，再调 /file 拉回二进制
    自己解析。session_id 可选（早期客户端没有 session 概念也能用）。
    """
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if file.content_type not in ALLOWED_CONTENT_TYPES and ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type: content_type={file.content_type}, ext={ext}. Allowed: .pdf",
        )
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=415, detail=f"扩展名 {ext} 不支持，仅接受 .pdf")

    content = b""
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        content += chunk
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="file too large (>50MB)")

    if len(content) < MIN_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="file too small / empty")

    job_id = uuid.uuid4()
    tmp_path = _get_tmp_dir() / f"{job_id}{ext or '.bin'}"
    tmp_path.write_bytes(content)

    job = DocumentImportJob(
        id=job_id,
        project_id=project_id,
        session_id=session_id,
        document_id=None,  # 客户端解析完自己写本地 DB，sp-api 不存 doc id
        user_id=current_user.id,
        original_filename=file.filename,
        file_path=str(tmp_path),
        status="uploaded",
    )
    db.add(job)
    await db.commit()

    return ImportPdfResponse(
        job_id=job_id,
        filename=file.filename or "",
        status="uploaded",
        size=len(content),
    )


@router.get("/documents/import-jobs/{job_id}", response_model=ImportJobStatus)
async def get_import_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查 job 状态。"""
    job = await db.get(DocumentImportJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="job not found")
    return ImportJobStatus(
        job_id=job.id,
        project_id=job.project_id,
        session_id=job.session_id,
        user_id=job.user_id,
        original_filename=job.original_filename,
        status=job.status,
        failure_reason=job.failure_reason,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/documents/import-jobs/{job_id}/cancel")
async def cancel_import_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DocumentImportJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="job not found")

    if job.status in ("ready", "cancelled"):
        return {"status": job.status, "already_terminal": True}

    if job.file_path and os.path.exists(job.file_path):
        try:
            os.remove(job.file_path)
        except OSError as e:
            logger.warning("[cancel] remove %s failed: %s", job.file_path, e)

    job.status = "cancelled"
    job.failure_reason = "user_cancelled"
    job.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"status": "cancelled"}


@router.get("/documents/import-jobs/{job_id}/file")
async def serve_import_file(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """下载原始上传文件。客户端解析时调一次拉回去。"""
    job = await db.get(DocumentImportJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="job not found")
    if not job.file_path:
        raise HTTPException(status_code=404, detail="file not stored")

    file_path = Path(job.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="file expired")

    return FileResponse(
        str(file_path),
        media_type="application/pdf",
        filename=job.original_filename or file_path.name,
    )
