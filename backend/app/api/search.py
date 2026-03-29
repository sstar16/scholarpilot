from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid
import asyncio

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.search_round import SearchRound
from app.models.round_document import RoundDocument
from app.models.document import Document
from app.models.feedback import Feedback
from app.schemas.search import RoundStatusOut, DocumentOut, RoundResultsOut
from app.services.progressive_search import create_next_round, mark_round_searching
from app.services.fetchers.base import FetcherRegistry

router = APIRouter(prefix="/api/projects", tags=["search"])


@router.post("/{project_id}/rounds/start", response_model=RoundStatusOut, status_code=201)
async def start_round(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建并启动下一轮检索"""
    project = await _get_project_or_404(project_id, current_user.id, db)

    from app.services.query_builder import get_max_rounds
    max_rounds = project.max_rounds or get_max_rounds(project.search_config)
    if project.current_round >= max_rounds:
        raise HTTPException(status_code=400, detail=f"已完成全部{max_rounds}轮检索，进入监控模式")

    # 检查当前轮次是否已完成
    if project.current_round > 0:
        result = await db.execute(
            select(SearchRound).where(
                SearchRound.project_id == project_id,
                SearchRound.round_number == project.current_round,
            )
        )
        current = result.scalar_one_or_none()
        if current and current.status not in ("complete", "failed"):
            raise HTTPException(
                status_code=400,
                detail=f"第{project.current_round}轮尚未完成（当前状态: {current.status}）",
            )

    # 创建下一轮
    round_ = await create_next_round(project, db)
    await db.commit()

    # 分发 Celery 任务
    from app.workers.search_tasks import execute_round
    execute_round.delay(str(round_.id))

    return round_


@router.get("/{project_id}/rounds/{round_id}/status", response_model=RoundStatusOut)
async def get_round_status(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    round_ = await _get_round_or_404(project_id, round_id, current_user.id, db)
    return round_


@router.get("/{project_id}/rounds/{round_id}/results", response_model=RoundResultsOut)
async def get_round_results(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    round_ = await _get_round_or_404(project_id, round_id, current_user.id, db)

    # 获取本轮文档（含摘要）
    result = await db.execute(
        select(RoundDocument, Document)
        .join(Document, RoundDocument.document_id == Document.id)
        .where(RoundDocument.round_id == round_id)
        .order_by(RoundDocument.rank_in_round)
    )
    rows = result.all()

    # 获取当前用户对这些文档的反馈
    doc_ids = [row.Document.id for row in rows]
    feedbacks = {}
    if doc_ids:
        fb_result = await db.execute(
            select(Feedback).where(
                Feedback.user_id == current_user.id,
                Feedback.round_id == round_id,
                Feedback.document_id.in_(doc_ids),
            )
        )
        for fb in fb_result.scalars().all():
            feedbacks[fb.document_id] = fb.relevance

    docs_out = []
    for rd, doc in rows:
        pub_date_str = doc.publication_date.isoformat() if doc.publication_date else None
        docs_out.append(DocumentOut(
            id=doc.id,
            source=doc.source,
            external_id=doc.external_id,
            doc_type=doc.doc_type,
            title=doc.title,
            title_zh=doc.title_zh,
            authors=doc.authors,
            abstract=doc.abstract,
            publication_date=pub_date_str,
            url=doc.url,
            doi=doc.doi,
            journal=doc.journal,
            citation_count=doc.citation_count or 0,
            pdf_url=doc.pdf_url,
            ai_summary=doc.ai_summary,
            ai_key_points=doc.ai_key_points,
            ai_relevance_reason=doc.ai_relevance_reason,
            ai_summary_source=doc.ai_summary_source,
            quality_score=doc.quality_score,
            rank_in_round=rd.rank_in_round,
            initial_score=rd.initial_score,
            user_feedback=feedbacks.get(doc.id),
        ))

    return RoundResultsOut(
        round_id=round_.id,
        round_number=round_.round_number,
        status=round_.status,
        documents=docs_out,
        total_candidates=round_.total_candidates,
    )


@router.get("/{project_id}/rounds", response_model=List[RoundStatusOut])
async def list_rounds(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, current_user.id, db)
    result = await db.execute(
        select(SearchRound)
        .where(SearchRound.project_id == project_id)
        .order_by(SearchRound.round_number)
    )
    return result.scalars().all()


@router.websocket("/ws/rounds/{round_id}")
async def ws_round_status(websocket: WebSocket, round_id: uuid.UUID):
    """WebSocket：实时推送轮次进度"""
    await websocket.accept()
    try:
        from app.database import AsyncSessionLocal
        while True:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(SearchRound).where(SearchRound.id == round_id))
                round_ = result.scalar_one_or_none()
                if not round_:
                    await websocket.send_json({"error": "round not found"})
                    break
                await websocket.send_json({
                    "status": round_.status,
                    "progress": round_.progress,
                    "message": round_.progress_message,
                })
                if round_.status in ("awaiting_feedback", "complete", "failed"):
                    break
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass


async def _get_project_or_404(project_id, user_id, db):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


async def _get_round_or_404(project_id, round_id, user_id, db):
    # 先验证项目归属
    await _get_project_or_404(project_id, user_id, db)
    result = await db.execute(
        select(SearchRound).where(
            SearchRound.id == round_id,
            SearchRound.project_id == project_id,
        )
    )
    round_ = result.scalar_one_or_none()
    if not round_:
        raise HTTPException(status_code=404, detail="轮次不存在")
    return round_
