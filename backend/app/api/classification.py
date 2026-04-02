"""文档分类 API — 4桶系统"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.document import Document
from app.models.document_classification import DocumentClassification
from app.models.round_document import RoundDocument
from app.schemas.classification import (
    ClassifyRequest,
    MoveRequest,
    ClassificationOut,
    BucketSummary,
    BucketDocumentOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["classification"])


@router.put("/{project_id}/documents/{document_id}/classify", response_model=ClassificationOut)
async def classify_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: ClassifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """将文档分类到桶（upsert）"""
    await _verify_project(project_id, current_user.id, db)

    # 验证文档存在
    doc = await db.execute(select(Document).where(Document.id == document_id))
    if not doc.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="文档不存在")

    # 查找当前轮次（用于 classified_in_round_id）
    round_id = await _get_active_round_id(project_id, db)

    # Upsert
    existing = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id == document_id,
        )
    )
    classification = existing.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if classification:
        old_bucket = classification.bucket
        classification.bucket = req.bucket
        classification.reason = req.reason or classification.reason
        classification.moved_at = now if old_bucket != req.bucket else classification.moved_at
    else:
        classification = DocumentClassification(
            user_id=current_user.id,
            project_id=project_id,
            document_id=document_id,
            bucket=req.bucket,
            classified_in_round_id=round_id,
            reason=req.reason,
            classified_at=now,
        )
        db.add(classification)

    await db.commit()
    await db.refresh(classification)

    logger.info("[Classification] doc=%s → bucket=%s (project=%s)", document_id, req.bucket, project_id)
    return classification


@router.put("/{project_id}/documents/{document_id}/move", response_model=ClassificationOut)
async def move_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: MoveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """桶间移动文档"""
    await _verify_project(project_id, current_user.id, db)

    result = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id == document_id,
        )
    )
    classification = result.scalar_one_or_none()
    if not classification:
        raise HTTPException(status_code=404, detail="该文档尚未分类")

    classification.bucket = req.to_bucket
    classification.moved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(classification)
    return classification


@router.delete("/{project_id}/documents/{document_id}/classify", status_code=204)
async def unclassify_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消分类"""
    await _verify_project(project_id, current_user.id, db)

    result = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id == document_id,
        )
    )
    classification = result.scalar_one_or_none()
    if classification:
        await db.delete(classification)
        await db.commit()


@router.get("/{project_id}/buckets", response_model=BucketSummary)
async def get_buckets(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取项目4个桶的全部内容"""
    await _verify_project(project_id, current_user.id, db)

    result = await db.execute(
        select(DocumentClassification, Document)
        .join(Document, DocumentClassification.document_id == Document.id)
        .where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
        )
        .order_by(DocumentClassification.classified_at.desc())
    )

    buckets = {"very_relevant": [], "relevant": [], "uncertain": [], "irrelevant": []}
    counts = {"very_relevant": 0, "relevant": 0, "uncertain": 0, "irrelevant": 0}

    for cls, doc in result.all():
        # 获取最佳 agent_score（跨轮次取最高分）
        best_score_q = await db.execute(
            select(func.max(RoundDocument.agent_score)).where(
                RoundDocument.document_id == doc.id
            )
        )
        best_score = best_score_q.scalar()

        item = BucketDocumentOut(
            document_id=doc.id,
            title=doc.title or "",
            one_line_summary=doc.one_line_summary,
            source=doc.source,
            agent_score=best_score,
            classified_at=cls.classified_at,
            bucket=cls.bucket,
        )
        if cls.bucket in buckets:
            buckets[cls.bucket].append(item)
            counts[cls.bucket] += 1

    return BucketSummary(**buckets, counts=counts)


# ── helpers ──

async def _verify_project(project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")


async def _get_active_round_id(project_id: uuid.UUID, db: AsyncSession):
    """获取当前活跃轮次 ID（用于记录分类来源）"""
    from app.models.search_round import SearchRound
    result = await db.execute(
        select(SearchRound.id)
        .where(SearchRound.project_id == project_id)
        .order_by(SearchRound.round_number.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row
