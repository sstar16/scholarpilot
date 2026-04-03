import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import uuid

logger = logging.getLogger(__name__)

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.search_round import SearchRound
from app.models.document import Document
from app.models.round_document import RoundDocument
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackSubmit, FeedbackResponse
from app.services.progressive_search import mark_round_complete
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
    # 验证项目和轮次归属
    project = await _get_project_or_404(project_id, current_user.id, db)
    round_ = await _get_round_or_404(round_id, project_id, db)

    # 动态最低评分数：文献数 ≤ 3 时需全部评完，否则至少评 3 篇
    total_docs_result = await db.execute(
        select(RoundDocument).where(RoundDocument.round_id == round_id)
    )
    total_docs = len(total_docs_result.scalars().all())
    min_required = total_docs if total_docs <= 3 else 3
    if len(req.feedbacks) < min_required:
        raise HTTPException(
            status_code=400,
            detail=f"请对全部{total_docs}篇文献评分后再继续" if total_docs <= 3
                   else "至少需要对3篇文献评分才能继续"
        )

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
                    "ai_key_points": doc.ai_key_points or [],
                },
            })

    await db.flush()

    # 用 LLM 从反馈原因中提取结构化信号（正向/负向关键词），丰富画像更新质量
    if feedback_dicts and any(fb.get("reason") for fb in feedback_dicts):
        try:
            from app.services.core.llm_config_store import get_llm_manager
            from app.services.llm_summarizer import LLMSummarizer
            llm_manager = await get_llm_manager()
            summarizer = LLMSummarizer(llm_manager)
            for fb_dict in feedback_dicts:
                if fb_dict.get("reason") and len(fb_dict["reason"]) >= 5:
                    pos_sig, neg_sig = await summarizer.extract_feedback_signals(
                        reason=fb_dict["reason"],
                        relevance=fb_dict["relevance"],
                    )
                    fb_dict["positive_signals"] = pos_sig
                    fb_dict["negative_signals"] = neg_sig
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[feedback] 信号提取失败，画像仅用基础关键词: %s", e)

    # [Harness] PRE_FEEDBACK hook
    try:
        from app.harness.hook_engine import HookEngine, HookPoint
        _hooks = HookEngine.get_instance()
        await _hooks.fire(HookPoint.PRE_FEEDBACK, {
            "round_id": str(round_id),
            "feedback_count": len(feedback_dicts),
            "project_id": str(project_id),
        })
    except Exception as _he:
        logger.warning("[Harness] hook error: %s", _he)

    # 更新用户画像（关键词频率方式）
    if feedback_dicts:
        await update_profile_from_feedbacks(current_user.id, project_id, feedback_dicts, db)

    # [Harness] Memory Agent — LLM 驱动的记忆更新（与关键词方式并行，互为冗余）
    from app.config import settings as _cfg
    if feedback_dicts and _cfg.enable_scoring_agent:
        try:
            from app.harness.memory_agent import run_memory_update
            from app.services.core.llm_config_store import get_llm_manager

            _llm_mem = await get_llm_manager()

            # 丰富 feedback_dicts 以包含 one_line_summary
            for fd in feedback_dicts:
                doc_obj = fd.get("document", {})
                doc_id = fd.get("document_id")
                if doc_id:
                    rd_q = await db.execute(
                        select(RoundDocument).where(
                            RoundDocument.round_id == round_id,
                            RoundDocument.document_id == doc_id,
                        )
                    )
                    rd_obj = rd_q.scalar_one_or_none()
                    if rd_obj:
                        fd["one_line_summary"] = rd_obj.one_line_summary or ""
                fd["title"] = doc_obj.get("title", "")
                fd["source"] = doc_obj.get("source", "")

            await run_memory_update(
                user_id=current_user.id,
                project_id=project_id,
                project_description=project.description,
                feedback_dicts=feedback_dicts,
                llm_manager=_llm_mem,
                db=db,
            )
        except Exception as e:
            logger.warning("[MemoryAgent] 记忆更新失败（不影响主流程）: %s", e)

    # 异步更新画像 embedding（不阻塞响应；下一轮检索开始前完成即可）
    from app.workers.embedding_tasks import update_profile_embedding
    update_profile_embedding.delay(str(current_user.id), str(project_id))

    # [Harness] POST_FEEDBACK hook
    try:
        await _hooks.fire(HookPoint.POST_FEEDBACK, {
            "round_id": str(round_id),
            "feedback_count": saved,
            "project_id": str(project_id),
        })
    except Exception as _he:
        logger.warning("[Harness] hook error: %s", _he)

    # 标记本轮完成（legacy 端点保留向后兼容，但不再自动推进轮次）
    await mark_round_complete(round_id, db)

    return FeedbackResponse(
        saved=saved,
        next_round_id=None,
        next_round_number=None,
        monitoring_activated=False,
        message=f"第{round_.round_number}轮反馈已保存（{saved}篇）。请使用「开始新一轮」或「结束本轮」按钮继续。",
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
