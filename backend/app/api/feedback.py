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
            from app.config import settings
            from app.services.core.llm_providers import LLMProviderManager
            from app.services.core.llm_config_store import load_llm_config
            from app.services.llm_summarizer import LLMSummarizer
            llm_manager = LLMProviderManager(default_ollama_host=settings.ollama_host)
            await load_llm_config(llm_manager, settings.redis_url)
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

    # 更新用户画像
    if feedback_dicts:
        await update_profile_from_feedbacks(current_user.id, project_id, feedback_dicts, db)

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

    # 标记本轮完成
    await mark_round_complete(round_id, db)

    # 决定下一步 — Autonomous Round Controller (or fallback to fixed rounds)
    next_round_id = None
    next_round_number = None
    monitoring_activated = False

    from app.services.query_builder import get_max_rounds
    from app.config import settings as _settings
    max_rounds = project.max_rounds or get_max_rounds(project.search_config)

    should_continue = project.current_round < max_rounds  # default: fixed rounds
    decision_reason = ""

    # [Harness] Autonomous round decision
    if _settings.enable_autonomous_rounds and project.current_round >= 1:
        try:
            from app.harness.round_controller import AutonomousRoundController
            from app.services.core.llm_providers import LLMProviderManager
            from app.services.core.llm_config_store import load_llm_config

            controller = AutonomousRoundController()
            _llm = LLMProviderManager(default_ollama_host=_settings.ollama_host)
            await load_llm_config(_llm, _settings.redis_url)

            # Build round history from DB
            all_rounds = await db.execute(
                select(SearchRound).where(
                    SearchRound.project_id == project_id
                ).order_by(SearchRound.round_number)
            )
            round_history = []
            for r in all_rounds.scalars().all():
                round_history.append({
                    "round_number": r.round_number,
                    "doc_count": r.total_candidates or 0,
                    "new_unique_count": r.selected_count if hasattr(r, "selected_count") else r.total_candidates or 0,
                })

            # Build feedback summary
            from sqlalchemy import func as sa_func
            total_rated_q = await db.execute(
                select(sa_func.count()).select_from(Feedback).where(Feedback.project_id == project_id)
            )
            positive_rated_q = await db.execute(
                select(sa_func.count()).select_from(Feedback).where(
                    Feedback.project_id == project_id, Feedback.relevance >= 1
                )
            )
            feedback_summary = {
                "total_rated": total_rated_q.scalar() or 0,
                "positive_rated": positive_rated_q.scalar() or 0,
            }

            decision = await controller.decide(
                project_description=project.description,
                completed_rounds=project.current_round,
                max_rounds=min(max_rounds, _settings.max_autonomous_rounds),
                round_history=round_history,
                feedback_summary=feedback_summary,
                llm_manager=_llm,
            )
            should_continue = decision.should_continue
            decision_reason = decision.reason
            logger.info(
                "[Harness] Round decision: continue=%s, reason=%s, confidence=%.2f",
                should_continue, decision_reason, decision.confidence,
            )
        except Exception as e:
            logger.warning("[Harness] Autonomous decision failed, using fixed rounds: %s", e)
            should_continue = project.current_round < max_rounds

    if should_continue:
        next_round = await create_next_round(project, db)
        await db.commit()
        next_round_id = next_round.id
        next_round_number = next_round.round_number

        # 当 per-source keywords 开启时，不自动 dispatch 搜索任务
        # 由前端调用 prepareRound → confirmKeywords 流程
        from app.config import settings as _settings
        if not _settings.enable_per_source_keywords:
            from app.workers.search_tasks import execute_round
            execute_round.delay(str(next_round.id))

        reason_suffix = f"（{decision_reason}）" if decision_reason else ""
        needs_confirm = _settings.enable_per_source_keywords
        if needs_confirm:
            message = f"第{round_.round_number}轮反馈已保存，请确认第{next_round_number}轮关键词后开始检索"
        else:
            message = f"第{round_.round_number}轮反馈已保存，AI 决定继续搜索{reason_suffix}，已启动第{next_round_number}轮"
    else:
        await activate_monitoring(project, db)
        monitoring_activated = True
        reason_suffix = f"（{decision_reason}）" if decision_reason else ""
        message = f"AI 决定停止搜索{reason_suffix}，已激活每日监控模式"

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
