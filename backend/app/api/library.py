"""Literature Library API — per-project markdown workspace browsing."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.user import User
from app.schemas.library import (
    LibraryDeleteBatchRequest,
    LibraryDeleteBatchResponse,
    LibraryDetailResponse,
    LibraryFileSummary,
    LibraryListResponse,
    LibraryRebuildResponse,
)
from app.services.literature_writer import LiteratureWriter, parse_frontmatter
from app.harness.file_tools.registry import tool_registry
from app.harness.file_tools.tools.fs_glob import FsGlobInput
from app.harness.file_tools.tools.fs_read import FsReadInput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["library"])


async def _verify_project(
    project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> None:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")


def _shape_list_entry(fm: dict) -> LibraryFileSummary:
    authors = fm.get("authors") or []
    if isinstance(authors, list) and authors:
        first = str(authors[0])
        plus = "+" if len(authors) > 1 else ""
        authors_short = f"{first}{plus}"
    else:
        authors_short = ""

    return LibraryFileSummary(
        slug=str(fm.get("slug") or ""),
        title=str(fm.get("title") or ""),
        title_zh=fm.get("title_zh"),
        authors_short=authors_short,
        year=fm.get("year"),
        bucket=fm.get("bucket"),
        quality_score=fm.get("quality_score"),
        updated_at=fm.get("updated_at"),
        extract_status=fm.get("extract_status"),
        document_id=str(fm["id"]) if fm.get("id") else None,
        source=fm.get("source"),
        external_id=fm.get("external_id"),
        doi=fm.get("doi"),
        url=fm.get("url"),
        pdf_url=fm.get("pdf_url"),
    )


@router.get("/{project_id}/library", response_model=LibraryListResponse)
async def list_library(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryListResponse:
    """扫 literature/*.md 动态返回列表，不依赖 _index.md。"""
    await _verify_project(project_id, current_user.id, db)

    writer = LiteratureWriter(str(project_id), tool_registry())
    try:
        glob_result = await writer.fs_glob.call(
            FsGlobInput(pattern="literature/*.md"),
            writer.ctx,
        )
    except Exception as e:
        logger.error("[LibAPI] glob failed project=%s: %s", str(project_id)[:8], e)
        return LibraryListResponse(total=0, by_bucket={}, files=[])

    files: list[LibraryFileSummary] = []
    by_bucket: dict[str, int] = {}
    for rel in glob_result.files:
        if rel.endswith("_index.md"):
            continue
        try:
            content = (
                await writer.fs_read.call(FsReadInput(path=rel), writer.ctx)
            ).content
            fm, _ = parse_frontmatter(content)
            if not fm:
                continue
            files.append(_shape_list_entry(fm))
            bucket = fm.get("bucket") or "uncategorized"
            by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
        except Exception as e:
            logger.warning("[LibAPI] skip %s: %s", rel, e)

    return LibraryListResponse(
        total=len(files),
        by_bucket=by_bucket,
        files=files,
    )


@router.get("/{project_id}/library/{slug}", response_model=LibraryDetailResponse)
async def get_library_detail(
    project_id: uuid.UUID,
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryDetailResponse:
    await _verify_project(project_id, current_user.id, db)

    writer = LiteratureWriter(str(project_id), tool_registry())
    rel = f"literature/{slug}.md"
    if not writer.sandbox.exists(rel):
        raise HTTPException(status_code=404, detail="文献未生成")

    try:
        raw = (await writer.fs_read.call(FsReadInput(path=rel), writer.ctx)).content
    except Exception as e:
        logger.error("[LibAPI] read failed slug=%s: %s", slug, e)
        raise HTTPException(status_code=500, detail="读取文件失败")

    fm, body = parse_frontmatter(raw)
    return LibraryDetailResponse(slug=slug, frontmatter=fm, body_md=body, raw=raw)


@router.get("/{project_id}/library/{slug}/raw")
async def get_library_raw(
    project_id: uuid.UUID,
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    await _verify_project(project_id, current_user.id, db)

    writer = LiteratureWriter(str(project_id), tool_registry())
    rel = f"literature/{slug}.md"
    if not writer.sandbox.exists(rel):
        raise HTTPException(status_code=404, detail="文献未生成")

    raw = (await writer.fs_read.call(FsReadInput(path=rel), writer.ctx)).content
    return PlainTextResponse(content=raw, media_type="text/markdown; charset=utf-8")


@router.post("/{project_id}/library/rebuild", response_model=LibraryRebuildResponse)
async def rebuild_library(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryRebuildResponse:
    await _verify_project(project_id, current_user.id, db)

    from app.workers.literature_tasks import backfill_library
    task = backfill_library.delay(str(project_id), False)
    return LibraryRebuildResponse(status="rebuilding", task_id=task.id)


@router.post(
    "/{project_id}/library/delete-batch",
    response_model=LibraryDeleteBatchResponse,
)
async def delete_library_batch(
    project_id: uuid.UUID,
    req: LibraryDeleteBatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryDeleteBatchResponse:
    """
    P1 批量删除：从**当前项目**移除 slug 对应的文献。

    级联：
      1. 从 frontmatter 读 document_id
      2. 删 DocumentClassification(project_id, document_id)
      3. 删 RoundDocument 所有属于该 project 的 round 关联
      4. 删 Feedback(project_id, document_id)
      5. 删 workspace/{pid}/literature/{slug}.md 文件
      6. 重建 _index.md

    **不删** global Document 表（多个项目可能引用同一篇）。
    """
    from sqlalchemy import delete as sa_delete
    from app.models.document_classification import DocumentClassification
    from app.models.round_document import RoundDocument
    from app.models.feedback import Feedback
    from app.models.search_round import SearchRound

    await _verify_project(project_id, current_user.id, db)
    writer = LiteratureWriter(str(project_id), tool_registry())

    deleted = 0
    failed: list[str] = []

    # 先拿到本项目的所有 round_ids（用于删 RoundDocument）
    r_ids = [r[0] for r in (
        await db.execute(select(SearchRound.id).where(SearchRound.project_id == project_id))
    ).all()]

    for slug in req.slugs:
        rel = f"literature/{slug}.md"
        try:
            if not writer.sandbox.exists(rel):
                failed.append(slug)
                continue
            # 1. 读 frontmatter 拿 document_id
            raw = (await writer.fs_read.call(FsReadInput(path=rel), writer.ctx)).content
            fm, _ = parse_frontmatter(raw)
            doc_id_str = fm.get("id") if fm else None

            # 2-4. DB 级联（只删与本项目相关的）
            if doc_id_str:
                try:
                    doc_uuid = uuid.UUID(str(doc_id_str))
                    await db.execute(
                        sa_delete(DocumentClassification).where(
                            DocumentClassification.project_id == project_id,
                            DocumentClassification.document_id == doc_uuid,
                        )
                    )
                    if r_ids:
                        await db.execute(
                            sa_delete(RoundDocument).where(
                                RoundDocument.round_id.in_(r_ids),
                                RoundDocument.document_id == doc_uuid,
                            )
                        )
                    await db.execute(
                        sa_delete(Feedback).where(
                            Feedback.project_id == project_id,
                            Feedback.document_id == doc_uuid,
                        )
                    )
                except ValueError:
                    logger.warning("[LibAPI/delete] invalid doc_id in fm: %s", doc_id_str)

            # 5. 删 markdown 文件
            abs_path = writer.sandbox.resolve(rel)
            if abs_path.exists():
                abs_path.unlink()

            deleted += 1
        except Exception as e:
            logger.warning("[LibAPI/delete] slug=%s failed: %s", slug, e)
            failed.append(slug)

    await db.commit()

    # 6. 重建 _index.md（best-effort）
    try:
        await writer.rebuild_index()
    except Exception as e:
        logger.warning("[LibAPI/delete] rebuild_index failed (benign): %s", e)

    # 统计剩余
    try:
        glob_result = await writer.fs_glob.call(
            FsGlobInput(pattern="literature/*.md"), writer.ctx,
        )
        remaining = len([p for p in glob_result.files if not p.endswith("_index.md")])
    except Exception:
        remaining = -1

    logger.info(
        "[LibAPI/delete] project=%s deleted=%d failed=%d remaining=%d",
        str(project_id)[:8], deleted, len(failed), remaining,
    )
    return LibraryDeleteBatchResponse(
        deleted=deleted, failed=failed, remaining_total=remaining,
    )
