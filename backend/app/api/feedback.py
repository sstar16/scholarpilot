from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import uuid

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.search_round import SearchRound
from app.models.document import Document
from app.models.round_document import RoundDocument
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackSubmit, FeedbackResponse
from app.services.progressive_search import mark_round_complete, create_next_round, activate_monitoring
from app.services.profile_service import update_profile_from_feedbacks

router = APIRouter(prefix="/api/projects", tags=["feedback"])


@router.post("/{project_id}/rounds/{round_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    req: FeedbackSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(req.feedbacks) < 3:
        raise HTTPException(status_code=400, detail="至少需要对3篇文献评分才能继续")

    # 验证项目和轮次归属
    project = await _get_project_or_404(project_id, current_user.id, db)
    round_ = await _get_round_or_404(round_id, project_id, db)

    if round_.status != "awaiting_feedback":
        raise HTTPException(status_code=400, detail=f"当前轮次状态为 {round_.status}，不在等待反馈阶段")

    # 保存反馈
    saved = 0
    feedback_dicts = []
    for fb_item in req.feedbacks:
        # 检查文档是否属于本轮
        rd_result = await db.execute(
            select(RoundDocument).where(
                RoundDocument.round_id == round_id,
                RoundDocument.document_id == fb_item.document_id,
            )
        )
        if not rd_result.scalar_one_or_none():
            continue

        # 获取文档（用于画像更新）
        doc_result = await db.execute(select(Document).where(Document.id == fb_item.document_id))
        doc = doc_result.scalar_one_or_none()

        # 更新或创建反馈
        existing = await db.execute(
            select(Feedback).where(
                Feedback.user_id == current_user.id,
                Feedback.round_id == round_id,
                Feedback.document_id == fb_item.document_id,
            )
        )
        feedback = existing.scalar_one_or_none()
        if feedback:
            feedback.relevance = fb_item.relevance
            feedback.reason = fb_item.reason
        else:
            feedback = Feedback(
                user_id=current_user.id,
                project_id=project_id,
                round_id=round_id,
                document_id=fb_item.document_id,
                relevance=fb_item.relevance,
                reason=fb_item.reason,
            )
            db.add(feedback)

        saved += 1
        if doc:
            feedback_dicts.append({
                "document_id": fb_item.document_id,
                "relevance": fb_item.relevance,
                "reason": fb_item.reason,
                "document": {
                    "title": doc.title,
                    "abstract": doc.abstract,
                    "source": doc.source,
                },
            })

    await db.flush()

    # 更新用户画像
    if feedback_dicts:
        await update_profile_from_feedbacks(current_user.id, project_id, feedback_dicts, db)

    # 标记本轮完成
    await mark_round_complete(round_id, db)

    # 异步触发反馈信号提取（不阻塞响应）
    for fb_item in req.feedbacks:
        if fb_item.reason:
            from app.workers.search_tasks import celery_app
            # Phase 2: 调用 extract_feedback_signals 任务

    # 决定下一步
    next_round_id = None
    next_round_number = None
    monitoring_activated = False

    if project.current_round < 5:
        next_round = await create_next_round(project, db)
        await db.commit()
        next_round_id = next_round.id
        next_round_number = next_round.round_number

        # 启动下一轮 Celery 任务
        from app.workers.search_tasks import execute_round
        execute_round.delay(str(next_round.id))

        message = f"第{round_.round_number}轮反馈已保存，已自动启动第{next_round_number}轮检索"
    else:
        await activate_monitoring(project, db)
        monitoring_activated = True
        message = "全部5轮检索完成，已激活每日监控模式"

    return FeedbackResponse(
        saved=saved,
        next_round_id=next_round_id,
        next_round_number=next_round_number,
        monitoring_activated=monitoring_activated,
        message=message,
    )


async def _get_project_or_404(project_id, user_id, db):
    from sqlalchemy import select
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    return p


async def _get_round_or_404(round_id, project_id, db):
    result = await db.execute(
        select(SearchRound).where(SearchRound.id == round_id, SearchRound.project_id == project_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="轮次不存在")
    return r
