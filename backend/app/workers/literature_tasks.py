"""
Celery tasks for literature workspace — S1 only has backfill.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)

MAX_BACKFILL_DOCS = 500


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.workers.literature_tasks.backfill_library",
    bind=True,
    max_retries=1,
)
def backfill_library(self, project_id: str, force: bool = False):
    """
    Backfill existing documents into .md workspace.
    Does NOT re-call LLM — uses existing DB fields (ai_summary / ai_key_points / abstract).
    """
    return _run_async(_backfill_async(project_id, force))


async def _backfill_async(project_id: str, force: bool):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.round_document import RoundDocument
    from app.models.search_round import SearchRound
    from app.models.document_classification import DocumentClassification
    from app.services.literature_writer import LiteratureWriter, make_slug
    from app.harness.file_tools.registry import tool_registry

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    processed, skipped, failed = 0, 0, 0

    try:
        async with session_factory() as db:
            result = await db.execute(
                select(Document)
                .join(RoundDocument, RoundDocument.document_id == Document.id)
                .join(SearchRound, SearchRound.id == RoundDocument.round_id)
                .where(SearchRound.project_id == uuid.UUID(project_id))
                .distinct()
                .limit(MAX_BACKFILL_DOCS)
            )
            docs = result.scalars().all()

            writer = LiteratureWriter(project_id, tool_registry())

            for doc in docs:
                slug = make_slug(str(doc.id), doc.title)
                rel = f"literature/{slug}.md"
                if writer.sandbox.exists(rel) and not force:
                    skipped += 1
                    continue

                bucket_q = await db.execute(
                    select(DocumentClassification.bucket).where(
                        DocumentClassification.project_id == uuid.UUID(project_id),
                        DocumentClassification.document_id == doc.id,
                    )
                )
                bucket = bucket_q.scalar_one_or_none()

                # 用"合并后的有效值"生成 .md：用户编辑的版本优先
                # 探针采纳的 excerpts 进 "探针原文抽取" section
                from app.harness.probe_cache import list_adopted_excerpts
                adopted_excerpts = list_adopted_excerpts(doc)

                llm_result = {
                    "summary": doc.effective_ai_summary or "",
                    "key_points": doc.effective_ai_key_points or [],
                    "one_line_summary": doc.effective_one_line_summary or "",
                    "quality_score": float(doc.quality_score or 0.0),
                    "concepts": [],
                    "methods": [],
                    "results": [],
                    "citations_mentioned": [],
                    "probe_excerpts": adopted_excerpts,
                    "_extract_status": "from_backfill",
                    "_user_edited": doc.user_edited_fields,
                }

                doc_dict = {
                    "id": str(doc.id),
                    "title": doc.title,
                    "authors": doc.authors,
                    "source": doc.source,
                    "external_id": doc.external_id,
                    "doi": doc.doi,
                    "journal": doc.journal,
                    "publication_date": str(doc.publication_date)
                    if doc.publication_date
                    else None,
                    "url": doc.url,
                    "pdf_url": doc.pdf_url,
                    "abstract": doc.abstract,
                    "ai_summary": doc.effective_ai_summary,
                    "ai_key_points": doc.effective_ai_key_points,
                    "one_line_summary": doc.effective_one_line_summary,
                    "quality_score": doc.quality_score,
                    "ai_summary_source": getattr(doc, "ai_summary_source", "from_backfill"),
                    "fulltext_text": bool(getattr(doc, "fulltext_text", None)),
                    "round_id": None,
                }

                try:
                    await writer.persist(doc_dict, bucket, llm_result)
                    processed += 1
                except Exception as e:
                    logger.error("[Backfill] doc=%s failed: %s", str(doc.id)[:8], e)
                    failed += 1

            try:
                await writer.rebuild_index()
            except Exception as e:
                logger.error("[Backfill] index rebuild failed: %s", e)

            logger.info(
                "[Backfill] project=%s processed=%d skipped=%d failed=%d",
                project_id[:8], processed, skipped, failed,
            )
            return {
                "processed": processed,
                "skipped": skipped,
                "failed": failed,
            }
    finally:
        await engine.dispose()
