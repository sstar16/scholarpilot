"""Celery tasks for document reverse-ingest flow (M2, extended in A1).

parse_pdf_metadata: 上传的文档 → markitdown_parser 抽文本 → DocImportAgent 提元数据
    （兼容 PDF + docx/pptx/xlsx/html/md/txt/csv 等 markitdown 支持的全部格式）
score_imported_document: 用户确认元数据后 → ScoringAgent 评分 + LiteratureWriter 写 md
cleanup_import_tmp_files: 每日 cron 清 24h 前的失败/取消 job 临时文件
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import app as celery_app
from app.harness.agents.doc_import_agent import DocImportAgent
from app.harness.agents.scoring_agent import ScoringAgent
from app.harness.file_tools.registry import tool_registry
from app.models.document import Document
from app.models.document_import_job import DocumentImportJob
from app.services.core.llm_config_store import get_llm_manager
from app.services.conversation_inject import inject_rich_message
from app.services.literature_writer import LiteratureWriter
from app.services.markitdown_parser import (
    DocumentParseError, extract_document_text, get_file_kind,
)

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Celery task 内运行 async code（每次新 event loop 避免泄漏）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@asynccontextmanager
async def _get_db():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.config import settings
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        yield db


# ───────────────────────────────────────────────────────────────────
# parse_pdf_metadata
# ───────────────────────────────────────────────────────────────────

@celery_app.task(name="app.workers.import_tasks.parse_pdf_metadata", bind=True, max_retries=1)
def parse_pdf_metadata(self, job_id: str):
    return _run_async(_parse_pdf_metadata_async(job_id))


async def _parse_pdf_metadata_async(job_id: str):
    async with _get_db() as db:
        job = await db.get(DocumentImportJob, uuid.UUID(job_id))
        if job is None:
            logger.error("[parse_pdf] job %s not found", job_id)
            return
        doc = await db.get(Document, job.document_id)

        try:
            # A1: markitdown 支持 docx/pptx/xlsx/html/md/... 全部自动分派
            # PDF 仍走 PyMuPDF（max_pages=3 只取头部做元数据抽取）
            kind = get_file_kind(job.original_filename or job.file_path)
            doc_text = extract_document_text(
                job.file_path,
                filename=job.original_filename,
                max_pdf_pages=3,
            )
            logger.info(
                "[parse_doc] job=%s kind=%s filename=%s len=%d",
                job_id, kind, job.original_filename, len(doc_text),
            )
            llm = await get_llm_manager()
            agent = DocImportAgent(llm)
            meta = await agent.extract(doc_text)

            # Update Document
            doc.title = meta.title or "(未识别标题)"
            doc.title_zh = meta.title_zh
            doc.authors = ", ".join(meta.authors) if meta.authors else None
            doc.abstract = meta.abstract or None
            doc.doi = meta.doi
            doc.journal = meta.journal
            doc.one_line_summary = meta.one_line_summary or None
            doc.concept_tags = meta.concept_tags or None
            if meta.year:
                from datetime import date as _date
                doc.publication_date = _date(meta.year, 1, 1)

            # Update Job
            job.status = "awaiting_edit"
            job.metadata_draft = {
                "title": meta.title,
                "title_zh": meta.title_zh,
                "authors": meta.authors,
                "year": meta.year,
                "abstract": meta.abstract,
                "doi": meta.doi,
                "journal": meta.journal,
                "one_line_summary": meta.one_line_summary,
                "concept_tags": meta.concept_tags,
            }
            await db.commit()

            # Push rich message — db first positional, then keyword args
            await inject_rich_message(
                db,
                rich_type="pdf_import_editing",
                content=f"已解析 {job.original_filename}，请核对元数据",
                rich_data={
                    "job_id": str(job.id),
                    "doc_id": str(doc.id),
                    "metadata_draft": job.metadata_draft,
                    "filename": job.original_filename,
                },
                session_id=job.session_id,
            )

        except Exception as e:
            logger.exception("[parse_pdf] job=%s failed: %s", job_id, e)
            job.status = "failed"
            job.failure_reason = str(e)[:500]
            await db.commit()
            try:
                await inject_rich_message(
                    db,
                    rich_type="pdf_import_failed",
                    content=f"PDF 解析失败：{job.failure_reason}",
                    rich_data={
                        "job_id": str(job.id),
                        "filename": job.original_filename,
                        "reason": job.failure_reason,
                    },
                    session_id=job.session_id,
                )
            except Exception:
                logger.exception("[parse_pdf] also failed to push error message")


# _extract_pdf_text 已迁移至 app.services.markitdown_parser._extract_pdf_text
# 外部仍可通过 extract_document_text(path, filename) 一键抽取任意支持格式


# ───────────────────────────────────────────────────────────────────
# Placeholders for Task 4 / 10
# ───────────────────────────────────────────────────────────────────

@celery_app.task(name="app.workers.import_tasks.score_imported_document", bind=True, max_retries=2)
def score_imported_document(self, job_id: str):
    return _run_async(_score_imported_document_async(job_id))


async def _score_imported_document_async(job_id: str):
    from sqlalchemy import select
    from app.models.project import Project
    from app.models.user_profile import UserProfile

    async with _get_db() as db:
        job = await db.get(DocumentImportJob, uuid.UUID(job_id))
        if job is None:
            logger.error("[score_import] job %s not found", job_id)
            return

        doc = await db.get(Document, job.document_id)
        project = await db.get(Project, job.project_id)

        try:
            # 仅当 project 完全缺失才跳过评分；首轮（current_round=0）也用
            # project.title/description 作为 project_description 给 ScoringAgent 评分，
            # user_memory 允许为空（画像还没建立）。
            skip_scoring = project is None

            if not skip_scoring:
                profile_res = await db.execute(
                    select(UserProfile).where(
                        UserProfile.user_id == job.user_id,
                        UserProfile.project_id == project.id,
                    )
                )
                profile = profile_res.scalar_one_or_none()

                user_memory = ""
                if profile is not None:
                    interests = getattr(profile, "interests", None) or ""
                    avoid = getattr(profile, "avoid", None) or ""
                    user_memory = f"兴趣：{interests}；回避：{avoid}"

                doc_dict = {
                    "id": str(doc.id),
                    "title": doc.title,
                    "title_zh": doc.title_zh,
                    "authors": doc.authors,
                    "abstract": doc.abstract,
                    "journal": doc.journal,
                    "publication_date": str(doc.publication_date) if doc.publication_date else None,
                    "doi": doc.doi,
                    "source": doc.source,
                }

                llm = await get_llm_manager()
                agent = ScoringAgent(llm_manager=llm)
                project_description = (
                    f"{project.title or ''}\n{project.description or ''}"
                ).strip()
                result = await agent.score_single(
                    doc=doc_dict,
                    project_description=project_description,
                    user_memory=user_memory,
                )

                if not result.scoring_failed:
                    doc.quality_score = result.agent_score
                    if result.one_line_summary and not doc.one_line_summary:
                        doc.one_line_summary = result.one_line_summary

            # ── 补全智能摘要 / 关键点 / 相关性理由（与检索流程 LLMSummarizer 输出对齐）──
            from app.services.llm_summarizer import LLMSummarizer
            try:
                summarizer = LLMSummarizer(llm if 'llm' in dir() else await get_llm_manager())
                sum_result = await summarizer.generate_summary(
                    doc={
                        "title": doc.title,
                        "abstract": doc.abstract,
                        "fulltext_text": doc.fulltext_text,
                    },
                    project_description=(
                        f"{project.title or ''}\n{project.description or ''}".strip()
                        if project else ""
                    ),
                    use_fulltext=bool(doc.fulltext_text),
                )
                if sum_result.get("summary"):
                    doc.ai_summary = sum_result["summary"]
                doc.ai_key_points = sum_result.get("key_points") or []
                if sum_result.get("relevance_reason"):
                    doc.ai_relevance_reason = sum_result["relevance_reason"]
                doc.ai_summary_source = sum_result.get("summary_source") or (
                    "from_fulltext" if doc.fulltext_text else "from_abstract"
                )
            except Exception as _sum_err:
                logger.warning("[score_import] LLMSummarizer failed for doc %s: %s", doc.id, _sum_err)
                # 兜底：至少标记数据源
                doc.ai_summary_source = "from_fulltext" if doc.fulltext_text else "from_abstract"

            writer = LiteratureWriter(str(project.id), tool_registry())
            slug = await writer.persist(
                doc={
                    "id": str(doc.id),
                    "title": doc.title,
                    "title_zh": doc.title_zh,
                    "authors": doc.authors,
                    "source": doc.source,
                    "external_id": doc.external_id,
                    "doi": doc.doi,
                    "journal": doc.journal,
                    "publication_date": doc.publication_date,
                    "url": doc.url,
                    "pdf_url": doc.pdf_url,
                    "abstract": doc.abstract,
                    "ai_summary": doc.ai_summary,
                    "ai_key_points": doc.ai_key_points,
                    "one_line_summary": doc.one_line_summary,
                    "quality_score": doc.quality_score,
                    "fulltext_text": doc.fulltext_text,
                    "ai_summary_source": doc.ai_summary_source,
                },
                bucket=None,
                llm_result={
                    "concepts": [
                        {"name": t, "type": "tag", "confidence": 0.6}
                        for t in (doc.concept_tags or [])
                    ],
                    "methods": [],
                    "results": [],
                    "citations_mentioned": [],
                    "summary": doc.ai_summary,
                    "key_points": doc.ai_key_points or [],
                    "one_line_summary": doc.one_line_summary,
                    "_extract_status": "import_ok",
                },
            )

            job.status = "ready"
            await db.commit()

            await inject_rich_message(
                db,
                session_id=job.session_id,
                rich_type="pdf_import_final_card",
                content=f"《{doc.title}》已就绪，请选择 4 桶之一",
                rich_data={
                    "job_id": str(job.id),
                    "doc_id": str(doc.id),
                    "slug": slug,
                    "evaluation_skipped": skip_scoring,
                },
            )

        except Exception as e:
            logger.exception("[score_import] job=%s failed: %s", job_id, e)
            job.status = "failed"
            job.failure_reason = str(e)[:500]
            await db.commit()
            try:
                await inject_rich_message(
                    db,
                    session_id=job.session_id,
                    rich_type="pdf_import_failed",
                    content=f"评分阶段失败：{job.failure_reason}",
                    rich_data={
                        "job_id": str(job.id),
                        "filename": job.original_filename,
                        "reason": job.failure_reason,
                    },
                )
            except Exception:
                logger.exception("[score_import] failed to push error message")


@celery_app.task(name="app.workers.import_tasks.cleanup_import_tmp_files")
def cleanup_import_tmp_files():
    return _run_async(_cleanup_async())


async def _cleanup_async():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    async with _get_db() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(DocumentImportJob).where(
                DocumentImportJob.status.in_(["failed", "cancelled"]),
                DocumentImportJob.created_at < cutoff,
            )
        )
        jobs = result.scalars().all()
        removed = 0
        for job in jobs:
            if job.file_path and os.path.exists(job.file_path):
                try:
                    os.remove(job.file_path)
                    removed += 1
                except OSError as e:
                    logger.warning("[cleanup] remove %s failed: %s", job.file_path, e)
        logger.info("[cleanup] removed %d stale PDFs", removed)
