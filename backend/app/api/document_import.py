"""M2 document import endpoints (A1: extended to multi-format via markitdown)."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_current_user_flexible
from app.models.document import Document
from app.models.document_import_job import DocumentImportJob
from app.models.conversation_session import ConversationSession
from app.models.user import User
from app.schemas.document_import import (
    ImportPdfResponse, ImportConfirmRequest, ImportConfirmResponse,
)
from app.services.conversation_inject import inject_rich_message
from app.services.markitdown_parser import ALL_SUPPORTED_EXTS, is_supported
from app.workers.import_tasks import parse_pdf_metadata, score_imported_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["document-import"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MIN_UPLOAD_BYTES = 200
# Backwards-compat aliases (referenced elsewhere)
MAX_PDF_BYTES = MAX_UPLOAD_BYTES
MIN_PDF_BYTES = MIN_UPLOAD_BYTES

# A1: MIME 白名单放宽（PDF + Office + HTML + 文本）；
# 浏览器对 docx/pptx/xlsx 的 content_type 上报不稳定（有时是 application/octet-stream），
# 所以最终判定以扩展名 is_supported() 为准，content_type 仅做初筛。
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/html",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/xml",
    "application/epub+zip",
    "application/vnd.ms-outlook",
    "application/octet-stream",  # 兜底：扩展名合法就放行
    "",  # 某些 curl / 工具不带 content_type
}


def _get_tmp_dir() -> Path:
    base = os.environ.get("PDF_STORAGE_PATH", "/app/data/fulltext")
    tmp = Path(base) / "import_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


@router.post(
    "/projects/{project_id}/documents/import-pdf",
    response_model=ImportPdfResponse,
)
async def import_pdf(
    project_id: uuid.UUID,
    session_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 1. Validate content type + filename extension
    #    MIME 白名单只做初筛；真正判定用扩展名（浏览器对 docx/pptx 的 MIME 上报不稳定）
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if file.content_type not in ALLOWED_CONTENT_TYPES and ext not in ALL_SUPPORTED_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type: content_type={file.content_type}, ext={ext}",
        )
    if not is_supported(filename):
        supported = ", ".join(sorted(ALL_SUPPORTED_EXTS))
        raise HTTPException(
            status_code=415,
            detail=f"unsupported extension '{ext}'. Allowed: {supported}",
        )

    # 2. Validate session ownership
    session = await db.get(ConversationSession, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="session not found")

    # 3. Stream + size check
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

    # 4. Allocate doc + job, write temp file (preserve original extension for parser)
    job_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    tmp_path = _get_tmp_dir() / f"{job_id}{ext or '.bin'}"
    tmp_path.write_bytes(content)

    doc = Document(
        id=doc_id,
        source="manual_upload",
        external_id=f"upload_{job_id.hex[:12]}",
        doc_type="paper",
        title="(解析中…)",
        import_source="manual_upload",
        imported_at=datetime.now(timezone.utc),
    )
    db.add(doc)

    job = DocumentImportJob(
        id=job_id,
        project_id=project_id,
        session_id=session_id,
        document_id=doc_id,
        user_id=current_user.id,
        original_filename=file.filename,
        file_path=str(tmp_path),
        status="parsing",
    )
    db.add(job)
    await db.commit()

    # 5. Dispatch Celery
    parse_pdf_metadata.delay(str(job_id))

    # 6. Push rich message
    await inject_rich_message(
        db,
        session_id=session_id,
        rich_type="pdf_import_parsing",
        content=f"已上传 {file.filename}，解析中...",
        rich_data={
            "job_id": str(job_id),
            "doc_id": str(doc_id),
            "filename": file.filename or "",
        },
    )
    await db.commit()

    return ImportPdfResponse(
        job_id=job_id,
        document_id=doc_id,
        filename=file.filename or "",
        status="parsing",
    )


@router.put(
    "/documents/{document_id}/import-confirm",
    response_model=ImportConfirmResponse,
)
async def confirm_import(
    document_id: uuid.UUID,
    req: ImportConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    result = await db.execute(
        select(DocumentImportJob).where(
            DocumentImportJob.document_id == document_id,
            DocumentImportJob.user_id == current_user.id,
        ).order_by(DocumentImportJob.created_at.desc())
    )
    jobs = result.scalars().all()
    if not jobs:
        raise HTTPException(status_code=404, detail="import job not found")
    job = jobs[0]
    # 幂等：若已在终态或 scoring 进行中，直接返回当前状态（用户可能刷新后重复点）
    if job.status in ("scoring", "ready", "cancelled", "failed"):
        return ImportConfirmResponse(
            job_id=job.id,
            document_id=document_id,
            next_status=job.status,
        )
    if job.status != "awaiting_edit":
        raise HTTPException(
            status_code=409,
            detail=f"job in unexpected state: {job.status}",
        )

    # Validation
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="title required")
    if not req.authors:
        raise HTTPException(status_code=400, detail="at least one author required")
    if not req.one_line_summary.strip():
        raise HTTPException(status_code=400, detail="one_line_summary required")

    # Update Document
    doc = await db.get(Document, document_id)
    doc.title = req.title.strip()
    doc.title_zh = req.title_zh
    doc.authors = ", ".join(req.authors)
    doc.abstract = req.abstract
    doc.doi = req.doi
    doc.journal = req.journal
    doc.one_line_summary = req.one_line_summary.strip()
    doc.concept_tags = req.concept_tags
    if req.year:
        from datetime import date
        doc.publication_date = date(req.year, 1, 1)

    # Resolve scene
    from app.services.project_scene import resolve_scene, ProjectScene
    scene = await resolve_scene(job.project_id, db)

    job.status = "scoring"
    await db.commit()

    # 注入进度气泡：让用户在 Celery 评分/摘要过程中看到 ScholarPilot 风格的进度动画
    try:
        await inject_rich_message(
            db,
            session_id=job.session_id,
            rich_type="pdf_import_scoring",
            content=f"ScholarPilot 正在为《{doc.title}》生成摘要与评分…",
            rich_data={
                "job_id": str(job.id),
                "doc_id": str(doc.id),
                "filename": job.original_filename or "",
            },
        )
    except Exception as _inj_err:
        logger.warning("[confirm_import] inject pdf_import_scoring failed: %s", _inj_err)

    score_imported_document.delay(str(job.id))

    return ImportConfirmResponse(
        job_id=job.id,
        document_id=doc.id,
        next_status="ready" if scene == ProjectScene.FRESH else "scoring",
    )


@router.post("/documents/import-jobs/{job_id}/cancel")
async def cancel_import_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select, func as sa_func
    from app.models.document_classification import DocumentClassification
    from app.models.round_document import RoundDocument

    job = await db.get(DocumentImportJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="job not found")

    # Idempotent for terminal states
    if job.status in ("ready", "cancelled"):
        return {"status": job.status, "already_terminal": True}

    # 1. Delete temp file
    if job.file_path and os.path.exists(job.file_path):
        try:
            os.remove(job.file_path)
        except OSError as e:
            logger.warning("[cancel] remove %s failed: %s", job.file_path, e)

    # 2. Mark job
    job.status = "cancelled"
    job.failure_reason = "user_cancelled"

    # 3. Delete placeholder document if orphaned
    clf_count = await db.scalar(
        select(sa_func.count()).select_from(DocumentClassification).where(
            DocumentClassification.document_id == job.document_id,
        )
    )
    rd_count = await db.scalar(
        select(sa_func.count()).select_from(RoundDocument).where(
            RoundDocument.document_id == job.document_id,
        )
    )
    if (clf_count or 0) == 0 and (rd_count or 0) == 0:
        doc = await db.get(Document, job.document_id)
        if doc and doc.import_source == "manual_upload":
            await db.delete(doc)

    await db.commit()

    # 4. Push rich message
    await inject_rich_message(
        db,
        session_id=job.session_id,
        rich_type="pdf_import_cancelled",
        content=f"已取消上传 {job.original_filename}",
        rich_data={
            "job_id": str(job.id),
            "filename": job.original_filename,
        },
    )
    await db.commit()

    return {"status": "cancelled"}


@router.get("/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single Document as DocumentCard-compatible dict.
    用于 PdfImportFinalCard 等需要完整文献数据但没有 round/project 上下文的前端组件。
    """
    from app.schemas.search import DocumentOut

    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    out = DocumentOut.model_validate(doc)
    payload = out.model_dump(mode="json")
    payload["import_source"] = doc.import_source

    # 手动上传的文档没有 RoundDocument 级评分字段，但 Document 上 quality_score/one_line_summary
    # 已经由 _score_imported_document_async 填充 → fallback 映射到前端期望的字段名，
    # 让 DocumentCard 的「AI 评分」「一句话总结」等元素能正常渲染。
    if doc.import_source == "manual_upload":
        if payload.get("agent_score") is None and doc.quality_score is not None:
            payload["agent_score"] = doc.quality_score
        if payload.get("one_line_summary") is None and doc.one_line_summary:
            payload["one_line_summary"] = doc.one_line_summary
    return payload


@router.get("/documents/{document_id}/original-pdf")
async def serve_original_upload(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """手动上传的原始文件下载（PDF / docx / etc.）—— 对应 DocumentCard 的「原文↗」按钮。"""
    doc = await db.get(Document, document_id)
    if doc is None or doc.import_source != "manual_upload":
        raise HTTPException(status_code=404, detail="无该上传文件")

    res = await db.execute(
        select(DocumentImportJob).where(
            DocumentImportJob.document_id == document_id,
            DocumentImportJob.user_id == current_user.id,
        ).limit(1)
    )
    job = res.scalar_one_or_none()
    if job is None or not job.file_path:
        raise HTTPException(status_code=404, detail="原始上传文件已清理")

    file_path = Path(job.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="原始上传文件已丢失")

    ext = file_path.suffix.lower()
    media_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
        ".htm": "text/html",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }
    return FileResponse(
        str(file_path),
        media_type=media_map.get(ext, "application/octet-stream"),
        filename=job.original_filename or file_path.name,
    )
