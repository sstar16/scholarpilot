import logging
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List
import uuid
import asyncio
import json
import os

logger = logging.getLogger(__name__)

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.search_round import SearchRound
from app.models.round_document import RoundDocument
from app.models.document import Document
from app.models.feedback import Feedback
from app.models.document_classification import DocumentClassification
from app.models.conversation_session import ConversationSession
from app.schemas.search import (
    RoundStatusOut, DocumentOut, RoundResultsOut, AnswerNowAcceptedOut,
)
from app.schemas.keywords import (
    KeywordGenerationResponse,
    SourceKeywordPlanOut,
    KeywordConfirmRequest,
)
from app.services.progressive_search import (
    create_next_round,
    mark_round_searching,
    mark_round_awaiting_keywords,
)
from app.services.fetchers.base import FetcherRegistry
from app.config import settings

router = APIRouter(prefix="/api/projects", tags=["search"])

# 允许"在此状态之后直接开启新一轮"的终态集合：
# complete/failed 是自然终点；cancelled/closed_no_feedback/closed 是用户主动退出的终点。
# 非终态（awaiting_keywords/awaiting_feedback/searching/…）由 prepare_round / start_round
# 内专门的分支决定 409（待反馈）/ 复用（等关键词）/ 400（进行中）。
_ROUND_TERMINAL_STATUSES = (
    "complete", "failed", "cancelled", "closed", "closed_no_feedback",
)


async def _assert_no_active_collab(project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> None:
    """
    三模式互斥：检查该 project 当前活跃的 session 是否处于协作 active。
    只看"最新一个 session"（按 updated_at 倒序），避免被僵尸 session 阻塞。
    """
    res = await db.execute(
        select(ConversationSession.current_state)
        .where(
            ConversationSession.project_id == project_id,
            ConversationSession.user_id == user_id,
            ConversationSession.is_active == True,  # noqa: E712
        )
        .order_by(ConversationSession.updated_at.desc())
        .limit(1)
    )
    latest_state = res.scalar_one_or_none()
    if latest_state == "collaboration_active":
        raise HTTPException(
            status_code=409,
            detail="喵喵！协作研究模式开着呢，不能同时开检索哦~ 先点「退出协作」放我出去，再来找新论文嘛。",
        )


@router.post("/{project_id}/rounds/start", response_model=RoundStatusOut, status_code=201)
async def start_round(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建并启动下一轮检索"""
    project = await _get_project_or_404(project_id, current_user.id, db)
    await _assert_no_active_collab(project_id, current_user.id, db)

    # 检查当前轮次是否已完成
    if project.current_round > 0:
        result = await db.execute(
            select(SearchRound).where(
                SearchRound.project_id == project_id,
                SearchRound.round_number == project.current_round,
            )
        )
        current = result.scalar_one_or_none()
        if current and current.status == "awaiting_feedback":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PENDING_ROUND_AWAITING_FEEDBACK",
                    "message": f"喵~第 {project.current_round} 轮还在等你分类文献呢，去文献库分完再开新一轮嘛！或者直接点「结束本轮」跳过反馈也行~",
                    "pending_round_id": str(current.id),
                    "pending_round_number": project.current_round,
                },
            )
        if current and current.status not in _ROUND_TERMINAL_STATUSES:
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

    # 获取当前用户对这些文档的反馈 (legacy) + 桶分类
    doc_ids = [row.Document.id for row in rows]
    feedbacks = {}
    buckets = {}
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

        cls_result = await db.execute(
            select(DocumentClassification).where(
                DocumentClassification.user_id == current_user.id,
                DocumentClassification.project_id == project_id,
                DocumentClassification.document_id.in_(doc_ids),
            )
        )
        for cls in cls_result.scalars().all():
            buckets[cls.document_id] = cls.bucket

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
            # 卡片编辑合并：_user 优先
            ai_summary=doc.effective_ai_summary,
            ai_key_points=doc.effective_ai_key_points,
            ai_relevance_reason=doc.ai_relevance_reason,
            ai_summary_source=doc.ai_summary_source,
            quality_score=doc.quality_score,
            rank_in_round=rd.rank_in_round,
            initial_score=rd.initial_score,
            agent_score=rd.agent_score,
            agent_rationale=rd.agent_rationale,
            one_line_summary=rd.one_line_summary or doc.effective_one_line_summary,
            below_cutoff=rd.below_cutoff or False,
            user_feedback=feedbacks.get(doc.id),
            bucket=buckets.get(doc.id),
            countries=doc.countries,
            fulltext_status=doc.fulltext_status,
            fulltext_path=doc.fulltext_path,
            fulltext_pdf_status=doc.fulltext_pdf_status,
            fulltext_pdf_path=doc.fulltext_pdf_path,
            fulltext_html_status=doc.fulltext_html_status,
            fulltext_html_path=doc.fulltext_html_path,
        ))

    return RoundResultsOut(
        round_id=round_.id,
        round_number=round_.round_number,
        status=round_.status,
        documents=docs_out,
        total_candidates=round_.total_candidates,
        source_stats=round_.source_stats,
        search_queries=round_.search_queries,
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


@router.post("/{project_id}/rounds/prepare", response_model=KeywordGenerationResponse, status_code=201)
async def prepare_round(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 1: 创建轮次 + 生成 per-source 关键词方案，等待用户确认"""
    if not settings.enable_per_source_keywords:
        raise HTTPException(status_code=400, detail="Per-source keywords feature is disabled")

    project = await _get_project_or_404(project_id, current_user.id, db)
    await _assert_no_active_collab(project_id, current_user.id, db)

    # 检查是否有已创建但未启动的轮次（由 feedback 端点预创建）
    existing_pending = None
    if project.current_round > 0:
        result = await db.execute(
            select(SearchRound).where(
                SearchRound.project_id == project_id,
                SearchRound.round_number == project.current_round,
            )
        )
        current = result.scalar_one_or_none()
        if current and current.status in ("pending", "awaiting_keywords"):
            existing_pending = current
        elif current and current.status == "awaiting_feedback":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PENDING_ROUND_AWAITING_FEEDBACK",
                    "message": f"喵~第 {project.current_round} 轮还在等你分类文献呢，去文献库分完再开新一轮嘛！或者直接点「结束本轮」跳过反馈也行~",
                    "pending_round_id": str(current.id),
                    "pending_round_number": project.current_round,
                },
            )
        elif current and current.status not in _ROUND_TERMINAL_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"第{project.current_round}轮尚未完成（当前状态: {current.status}）",
            )

    if existing_pending:
        round_ = existing_pending
    else:
        round_ = await create_next_round(project, db)
        await db.commit()

    # 构建查询计划（Agent-First）
    from app.services.query_builder import build_query, get_max_rounds
    from app.services.core.llm_config_store import get_llm_manager
    from app.models.user_profile import UserProfile

    llm_manager = await get_llm_manager()

    # 加载用户画像 + 项目记忆
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.project_id == project_id)
    )
    profile = profile_result.scalar_one_or_none()
    memory_text = profile.memory_text if profile else ""

    # Agent-First: 让 QueryPlanAgent 生成完整方案
    query_plan = None
    _plan_source = "fallback"
    _plan_rationale = ""

    # 提前读取 search_mode — static_db 只有 1 个源，Agentic 源选择/年份决策无意义，
    # 直接走 build_query()（仍含 LLM 翻译，对 FTS5 匹配英文文献有帮助）
    _proj_search_mode = (project.search_config or {}).get("search_mode")

    # 首轮 + ResearchDecisionAgent 预计算方案 → 直接使用，跳过 agentic_plan 自校验
    precomputed = (project.search_config or {}).get("precomputed_plan")
    if precomputed and round_.round_number == 1:
        try:
            from app.services.query_builder import QueryPlan as _PrecomputedQP
            _pre_base = (precomputed.get("base_query") or "").strip()
            query_plan = _PrecomputedQP(
                base_query=_pre_base,
                expanded_terms=[w for w in _pre_base.split() if len(w) >= 2],
                exclude_terms=[],
                year_from=precomputed.get("year_from"),
                year_to=precomputed.get("year_to"),
                sources=["local_kb"],  # search_mode filter 会覆盖
                max_results_per_source=20,
                language_scope=precomputed.get("language_scope", "international"),
                original_chinese_query=precomputed.get("chinese_query"),
            )
            query_plan._rationale = precomputed.get("rationale", "") or ""
            _plan_source = "precomputed"
            _plan_rationale = query_plan._rationale
            logger.info(
                "[prepare] 首轮使用 ResearchDecisionAgent 预计算方案: %r",
                query_plan.base_query[:60],
            )
        except Exception as e:
            logger.warning("[prepare] precomputed_plan 解析失败: %s", e)
            query_plan = None

    if query_plan is None and settings.enable_scoring_agent:
        try:
            from app.harness.agents.query_plan_agent import QueryPlanAgent
            from app.harness.tool_registry import ToolRegistry
            registry = ToolRegistry.get_instance()

            prev_stats = {}
            if round_.round_number > 1:
                prev_q = await db.execute(
                    select(SearchRound).where(
                        SearchRound.project_id == project_id,
                        SearchRound.round_number == round_.round_number - 1,
                    )
                )
                prev_r = prev_q.scalar_one_or_none()
                if prev_r and prev_r.source_stats:
                    prev_stats = prev_r.source_stats

            qp_agent = QueryPlanAgent(llm_manager=llm_manager)
            # 优先：tool-using agentic loop（自校验、模型变强自动变强）
            query_plan = await qp_agent.agentic_plan(
                project_description=project.description,
                memory_text=memory_text or "",
            )
            # Agentic 失败时回退到 legacy single-shot plan
            if query_plan is None:
                query_plan = await qp_agent.plan(
                    project_description=project.description,
                    memory_text=memory_text or "",
                    round_number=round_.round_number,
                    max_rounds=project.max_rounds or get_max_rounds(project.search_config),
                    tool_reliability=registry.get_reliability_report(),
                    prev_source_stats=prev_stats,
                )
            # Agent 判定用户描述过于模糊 → 直接返回 400 让用户补充
            if query_plan and getattr(query_plan, "_clarification_needed", False):
                msg = getattr(query_plan, "_clarification_message", "") or "研究描述不够具体，请补充关键词或研究场景"
                raise HTTPException(status_code=400, detail=f"【需要补充描述】{msg}")
            if query_plan:
                _plan_source = "agent"
                _plan_rationale = getattr(query_plan, '_rationale', '') or ''
        except Exception as e:
            logger.warning("[prepare] QueryPlanAgent 失败: %s", e)
            query_plan = None

    # Fallback
    if query_plan is None:
        preferred_kw = profile.preferred_keywords if profile else []
        excluded_kw = profile.excluded_keywords if profile else []
        query_plan = await build_query(
            project_description=project.description,
            project_domain=project.domain or "",
            round_number=round_.round_number,
            preferred_keywords=preferred_kw,
            excluded_keywords=excluded_kw,
            preferred_sources=project.search_config.get("preferred_sources") if project.search_config else None,
            llm_manager=llm_manager,
            search_config=project.search_config,
            project_domains=project.domains,
            project_title=project.title,
        )

    # 根据 search_mode 决定关键词生成策略（_proj_search_mode 已在上方读取）
    if _proj_search_mode == "static_db":
        # 静态数据源模式：仅 local_kb 一个源，但同样跑 LLM 优化关键词
        # （之前直接拼字符串，导致用户感觉"没过 LLM"）
        from app.services.source_query_adapters import generate_all_keywords
        keyword_result = await generate_all_keywords(
            round_id=str(round_.id),
            base_query=query_plan.base_query,
            original_chinese_query=query_plan.original_chinese_query,
            project_description=f"{project.title}。{project.description}" if project.title else project.description,
            sources=["local_kb"],
            llm_manager=llm_manager,
            disabled_sources=set(),
        )
        # 为 local_kb 加上中文显示名 + notes
        for plan in keyword_result.source_plans:
            if plan.source_id == "local_kb":
                plan.display_name = "本地知识库"
                plan.language = "multilingual"
                plan.notes = "本地知识库 · LLM 优化的中英双语关键词"
        logger.info("[prepare] static_db mode: LLM 优化 local_kb 关键词")
    else:
        # API / hybrid 模式：完整的 per-source 关键词优化
        from app.services.source_config_store import get_effective_disabled
        disabled_sources = await get_effective_disabled()

        from app.services.fetchers.international import ALL_FETCHERS
        all_available_sources = [sid for sid in ALL_FETCHERS.keys() if sid not in disabled_sources]

        from app.services.source_query_adapters import generate_all_keywords
        keyword_result = await generate_all_keywords(
            round_id=str(round_.id),
            base_query=query_plan.base_query,
            original_chinese_query=query_plan.original_chinese_query,
            project_description=f"{project.title}。{project.description}" if project.title else project.description,
            sources=all_available_sources,
            llm_manager=llm_manager,
            disabled_sources=disabled_sources,
        )

        # 2026-04-25 调整：default_enabled 不再盲目 set(all)，改为尊重 LLM 的源适配判断。
        # generate_all_keywords 已经对每个源标记了 method:
        #   - "llm"         → LLM 明确为此源生成了 query（适合当前主题）
        #   - "llm_skipped" → LLM 判定此源不适合当前主题，默认关闭
        #   - "heuristic" / "passthrough" → LLM 全挂时 fallback（保持原行为全 enable）
        # 这样用户打开 KeywordConfirmPanel 看到的是 LLM 推荐的 3-5 个源，而不是 10 个全勾选——
        # 避免"只想查 patenthub，结果跑了 10 个源"的 UX 事故。
        llm_chosen = {
            p.source_id for p in keyword_result.source_plans
            if p.generation_method == "llm"
        }
        llm_all_failed = not any(
            p.generation_method == "llm" for p in keyword_result.source_plans
        )

        if _proj_search_mode == "api":
            if llm_all_failed:
                # LLM 完全不可用 → 保留旧行为（所有非 local_kb 源默认 enabled）
                default_enabled = set(s for s in all_available_sources if s != "local_kb")
            else:
                default_enabled = llm_chosen - {"local_kb"}
        elif _proj_search_mode == "hybrid":
            if llm_all_failed:
                default_enabled = set(all_available_sources)
            else:
                default_enabled = llm_chosen | {"local_kb"}
        else:
            default_enabled = set(query_plan.sources)

        # 双向同步 plan.enabled 与 default_enabled：
        # - in default_enabled → 强制 True（修复 hybrid 模式 local_kb 因 LLM 没给 hint
        #   导致 generate_all_keywords 给的初值是 False，此处不强制 True 就永远不会被勾选）
        # - not in default_enabled → False（LLM 判定不适合，默认关闭，用户可手动开启）
        for plan in keyword_result.source_plans:
            if plan.source_id in default_enabled:
                plan.enabled = True
            else:
                plan.enabled = False
                skip_note = (
                    "LLM 判定此源不适合当前主题，默认关闭（可手动开启）"
                    if not llm_all_failed
                    else f"默认未启用（模式={_proj_search_mode or 'auto'}，可手动开启）"
                )
                plan.notes = (
                    f"{skip_note}；{plan.notes}" if plan.notes else skip_note
                )

    # 存入 Redis（TTL 10 分钟）
    import redis.asyncio as aioredis
    redis = aioredis.from_url(settings.redis_url)
    try:
        _plan_data = keyword_result.to_dict()
        # Inject search_mode from project.search_config（_proj_search_mode 在 prepare 开头已读取）
        if _proj_search_mode:
            _plan_data["search_mode"] = _proj_search_mode
        await redis.set(
            f"keyword_plan:{round_.id}",
            json.dumps(_plan_data),
            ex=600,
        )
    finally:
        await redis.close()

    # 更新 round 状态
    await mark_round_awaiting_keywords(round_.id, db)

    # 保存查询信息到 round
    await db.execute(
        update(SearchRound).where(SearchRound.id == round_.id).values(
            search_queries={
                "base_query": query_plan.base_query,
                "original_chinese_query": query_plan.original_chinese_query,
                "expanded_terms": query_plan.expanded_terms,
                "exclude_terms": query_plan.exclude_terms,
                "english_query_source": query_plan.english_query_source,
                "cn_query_source": query_plan.cn_query_source,
                "anchor_keywords": query_plan.anchor_keywords,
                "profile_injected_en": query_plan.profile_injected_en,
                "profile_injected_zh": query_plan.profile_injected_zh,
                "year_from": query_plan.year_from,
                "year_to": query_plan.year_to,
                "language_scope": query_plan.language_scope,
                "max_per_source": query_plan.max_results_per_source,
            }
        )
    )
    await db.commit()
    # 重新查询 round（长时间 LLM 调用后 ORM 对象可能已脱离 session）
    result = await db.execute(select(SearchRound).where(SearchRound.id == round_.id))
    round_ = result.scalar_one()

    # 往活跃对话 session 注入富消息：关键词确认气泡 + 同步 session 状态机
    try:
        from app.services.conversation_inject import (
            inject_rich_message,
            enter_keyword_confirmation_state,
        )
        await inject_rich_message(
            db,
            project_id=project_id,
            rich_type="keyword_confirmation",
            content=f"我为第 {round_.round_number} 轮检索生成了关键词方案，请确认",
            rich_data={
                "round_id": str(round_.id),
                "round_number": round_.round_number,
                "base_query": query_plan.base_query,
                "source_plans": [p.to_dict() for p in keyword_result.source_plans],
                "year_from": query_plan.year_from,
                "year_to": query_plan.year_to,
                "max_per_source": query_plan.max_results_per_source,
                "plan_source": _plan_source,
                "search_mode": _proj_search_mode,
            },
        )
        # session 从 FunctionDock "新检索" 路径直达关键词卡时，state_data.current_round_id
        # 必须同步写入 —— 否则后续 _exit_keyword / reset-for-new-round 无法定位要 cancel 的 round。
        await enter_keyword_confirmation_state(
            db, project_id=project_id, round_id=round_.id
        )
    except Exception as _inj_err:
        logger.warning("[prepare_round] inject keyword_confirmation failed: %s", _inj_err)

    return KeywordGenerationResponse(
        round_id=round_.id,
        round_number=round_.round_number,
        base_query=query_plan.base_query,
        original_chinese_query=query_plan.original_chinese_query,
        exclude_terms=query_plan.exclude_terms,
        year_from=query_plan.year_from,
        year_to=query_plan.year_to,
        max_per_source=query_plan.max_results_per_source,
        language_scope=query_plan.language_scope,
        plan_source=_plan_source,
        plan_rationale=_plan_rationale,
        english_query_source=query_plan.english_query_source,
        cn_query_source=query_plan.cn_query_source,
        source_plans=[SourceKeywordPlanOut(**p.to_dict()) for p in keyword_result.source_plans],
        generation_time_ms=keyword_result.generation_time_ms,
    )


@router.get("/{project_id}/rounds/{round_id}/keyword-plan")
async def get_keyword_plan(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取已生成的 per-source 关键词方案（用于页面刷新恢复）"""
    await _get_round_or_404(project_id, round_id, current_user.id, db)

    import redis.asyncio as aioredis
    redis = aioredis.from_url(settings.redis_url)
    try:
        raw = await redis.get(f"keyword_plan:{round_id}")
        if not raw:
            raise HTTPException(status_code=404, detail="关键词方案已过期，请重新启动检索")
        return json.loads(raw)
    finally:
        await redis.close()


@router.post("/{project_id}/rounds/{round_id}/confirm-keywords", response_model=RoundStatusOut)
async def confirm_keywords(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    body: KeywordConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 2: 用户确认关键词后，启动实际搜索"""
    if not settings.enable_per_source_keywords:
        raise HTTPException(status_code=400, detail="Per-source keywords feature is disabled")

    round_ = await _get_round_or_404(project_id, round_id, current_user.id, db)
    if round_.status != "awaiting_keywords":
        raise HTTPException(
            status_code=400,
            detail=f"轮次状态不正确（期望 awaiting_keywords，当前 {round_.status}）",
        )

    # 将用户确认的关键词 + QueryPlan 修改存入 Redis
    import redis.asyncio as aioredis
    redis = aioredis.from_url(settings.redis_url)
    try:
        confirmed_data = {
            "round_id": str(round_id),
            "source_plans": [p.model_dump() for p in body.source_plans],
            "confirmed": True,
        }
        # 用户编辑的 QueryPlan 参数覆盖
        if body.base_query is not None:
            confirmed_data["base_query"] = body.base_query
        if body.original_chinese_query is not None:
            confirmed_data["original_chinese_query"] = body.original_chinese_query
        if body.exclude_terms is not None:
            confirmed_data["exclude_terms"] = body.exclude_terms
        if body.year_from is not None:
            confirmed_data["year_from"] = body.year_from
        if body.year_to is not None:
            confirmed_data["year_to"] = body.year_to
        if body.max_per_source is not None:
            confirmed_data["max_per_source"] = body.max_per_source
        if body.language_scope is not None:
            confirmed_data["language_scope"] = body.language_scope
        if body.search_mode is not None:
            confirmed_data["search_mode"] = body.search_mode
        await redis.set(
            f"keyword_plan:{round_id}",
            json.dumps(confirmed_data),
            ex=600,
        )
    finally:
        await redis.close()

    # 更新状态为 pending，然后派发 Celery 任务
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(SearchRound).where(SearchRound.id == round_id).values(
            status="pending",
            progress=0.05,
            progress_message="关键词已确认，准备开始检索...",
        )
    )
    await db.commit()

    # 注入富消息：开始检索（后续 worker 会持续更新该消息的 rich_data）
    try:
        from app.services.conversation_inject import inject_rich_message
        # 这里 confirm_keywords 作用域里没有 project 对象，需要现查一次 search_mode
        _proj_cfg_row = await db.execute(
            select(Project.search_config).where(Project.id == project_id)
        )
        _proj_cfg = _proj_cfg_row.scalar_one_or_none() or {}
        _curr_search_mode = _proj_cfg.get("search_mode") if isinstance(_proj_cfg, dict) else None
        await inject_rich_message(
            db,
            project_id=project_id,
            rich_type="search_progress",
            content=f"第 {round_.round_number} 轮检索已启动",
            rich_data={
                "round_id": str(round_id),
                "round_number": round_.round_number,
                "status": "searching",
                "progress": 0.05,
                # 本轮实际使用的检索模式 — 让前端 mode badge 不用依赖 sourceStats
                "search_mode": _curr_search_mode,
            },
        )
    except Exception as _inj_err:
        logger.warning("[confirm_keywords] inject search_progress failed: %r", _inj_err)

    from app.workers.search_tasks import execute_round
    execute_round.delay(str(round_id))

    result = await db.execute(select(SearchRound).where(SearchRound.id == round_id))
    round_ = result.scalar_one()
    return round_


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


@router.post("/{project_id}/rounds/{round_id}/finalize")
async def finalize_round(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户手动结束本轮 — 触发 Memory Agent + Profile 更新"""
    project = await _get_project_or_404(project_id, current_user.id, db)
    round_ = await _get_round_or_404(project_id, round_id, current_user.id, db)

    if round_.status not in ("awaiting_feedback",):
        raise HTTPException(status_code=400, detail=f"轮次状态 {round_.status}，无法结束")

    # 收集本轮文档的桶分类
    rd_result = await db.execute(
        select(RoundDocument, Document)
        .join(Document, RoundDocument.document_id == Document.id)
        .where(RoundDocument.round_id == round_id)
    )
    rows = rd_result.all()
    doc_ids = [doc.id for _, doc in rows]

    cls_result = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id.in_(doc_ids),
        )
    ) if doc_ids else None

    classifications = {}
    if cls_result:
        for cls in cls_result.scalars().all():
            classifications[cls.document_id] = cls

    # 构建 feedback_dicts（兼容现有 profile_service + memory_agent）
    feedback_dicts = []
    bucket_to_relevance = {"very_relevant": 2, "relevant": 1, "uncertain": 0, "irrelevant": -1}
    for rd, doc in rows:
        cls = classifications.get(doc.id)
        if not cls:
            continue
        feedback_dicts.append({
            "document_id": doc.id,
            "relevance": bucket_to_relevance.get(cls.bucket, 0),
            "bucket": cls.bucket,
            "reason": cls.reason,
            "title": doc.title or "",
            "source": doc.source,
            "one_line_summary": rd.one_line_summary or doc.one_line_summary or "",
            "document": {
                "title": doc.title or "",
                "abstract": doc.abstract or "",
                "source": doc.source,
                "ai_key_points": doc.ai_key_points or [],
            },
        })

    # Profile 更新
    if feedback_dicts:
        from app.services.profile_service import update_profile_from_feedbacks
        await update_profile_from_feedbacks(current_user.id, project_id, feedback_dicts, db)

    # Memory Agent 更新
    from app.config import settings as _cfg
    if feedback_dicts and _cfg.enable_scoring_agent:
        try:
            from app.harness.agents.memory_agent import run_memory_update
            from app.services.core.llm_config_store import get_llm_manager

            _llm_mem = await get_llm_manager()

            await run_memory_update(
                user_id=current_user.id,
                project_id=project_id,
                project_description=project.description,
                feedback_dicts=feedback_dicts,
                llm_manager=_llm_mem,
                db=db,
            )
        except Exception as e:
            logger.warning("[finalize] Memory Agent 失败: %s", e)

    # 标记轮次完成
    from app.services.progressive_search import mark_round_complete
    await mark_round_complete(round_id, db)

    # 检索流程锁定结束：把该项目下所有卡在检索态的 session 切回 idle，
    # 让用户接下来能进协作 / 新检索
    LOCKED_SEARCH_STATES = (
        "intent_analysis", "intent_confirmation", "search_mode_selection",
        "keyword_confirmation", "searching", "scoring", "classification", "round_finalize",
    )
    await db.execute(
        update(ConversationSession)
        .where(
            ConversationSession.project_id == project_id,
            ConversationSession.user_id == current_user.id,
            ConversationSession.is_active == True,  # noqa: E712
            ConversationSession.current_state.in_(LOCKED_SEARCH_STATES),
        )
        .values(current_state="idle")
    )
    await db.commit()

    # [Harness] B3: ROUND_COMPLETE hook —— 触发 KG 增量刷新 + 其他下游动作
    try:
        from app.harness.hook_engine import HookEngine, HookPoint
        await HookEngine.get_instance().fire(HookPoint.ROUND_COMPLETE, {
            "round_id": str(round_id),
            "project_id": str(project_id),
            "feedback_count": len(feedback_dicts),
        })
    except Exception as _he:
        logger.warning("[Harness] ROUND_COMPLETE hook error: %s", _he)

    classified_count = len(feedback_dicts)
    total_count = len(rows)

    # 统计 4 桶分布
    bucket_counts = {"very_relevant": 0, "relevant": 0, "uncertain": 0, "irrelevant": 0}
    for fd in feedback_dicts:
        b = fd.get("bucket")
        if b in bucket_counts:
            bucket_counts[b] += 1

    # 注入富消息：轮次完成总结
    try:
        from app.services.conversation_inject import inject_rich_message
        _prev_search_mode = (project.search_config or {}).get("search_mode")
        _prev_source_stats = round_.source_stats or {}
        await inject_rich_message(
            db,
            project_id=project_id,
            rich_type="round_complete",
            content=f"第 {round_.round_number} 轮已结束，{classified_count}/{total_count} 篇已分类",
            rich_data={
                "round_id": str(round_id),
                "round_number": round_.round_number,
                "classified": classified_count,
                "total": total_count,
                "bucket_counts": bucket_counts,
                "memory_updated": bool(feedback_dicts and _cfg.enable_scoring_agent),
                # 把本轮的模式 + source_stats 一起带给前端，让 RoundCompleteMessage
                # 的"下一轮模式推荐"算法能基于真实数据做决策
                "search_mode": _prev_search_mode,
                "source_stats": _prev_source_stats,
            },
        )
    except Exception as _inj_err:
        logger.warning("[finalize_round] inject round_complete failed: %s", _inj_err)

    return {
        "status": "complete",
        "classified": classified_count,
        "total": total_count,
        "message": f"第{round_.round_number}轮已结束，{classified_count}/{total_count} 篇已分类",
    }


# 允许触发 Answer Now 的 round 状态: 必须在主流程 stage 内 (不含 awaiting_keywords —
# 那个阶段还没真正开始检索, partial 没意义).
_ANSWER_NOW_TRIGGERABLE_STATUSES = (
    "pending", "searching", "scoring", "saving", "summarizing",
)


@router.post(
    "/{project_id}/rounds/{round_id}/answer-now",
    status_code=202,
    response_model=AnswerNowAcceptedOut,
)
async def trigger_answer_now(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """触发 Answer Now 中断快通道.

    设 Redis flag, Celery worker 在下一个 stage 边界检测后用已有部分文献
    LLM 合成 partial 答案 -> 转 round.status='partial_complete' -> 推
    SSE 'partial_answer_ready'.

    返回 202 表示请求已受理 (不等 partial 生成完). 前端继续监听 SSE.
    """
    round_ = await _get_round_or_404(project_id, round_id, current_user.id, db)

    # 状态校验
    if round_.status not in _ANSWER_NOW_TRIGGERABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"喵呜 当前轮次状态是 {round_.status!r}, 不能触发 Answer Now. "
                f"只在 {list(_ANSWER_NOW_TRIGGERABLE_STATUSES)} 时可用."
            ),
        )

    # 设 Redis flag
    import redis.asyncio as aioredis
    from app.services.partial_synthesizer import set_interrupt_flag

    redis = aioredis.from_url(settings.redis_url)
    try:
        ok = await set_interrupt_flag(str(round_id), redis)
    finally:
        try:
            await redis.close()
        except Exception:
            pass

    if not ok:
        raise HTTPException(
            status_code=503,
            detail="Answer Now flag 写 Redis 失败, 请稍后再试.",
        )

    # SSE 立即提示用户 "已受理"
    try:
        from app.services.event_bus import EventBus
        EventBus.publish_sync(str(round_id), "round_status", {
            "status": round_.status,
            "progress": round_.progress,
            "message": (
                f"Answer Now 已受理, 当前阶段 ({round_.status}) 完成后立刻合成部分结果"
            ),
            "answer_now_pending": True,
        })
    except Exception as e:
        logger.warning("[answer_now] SSE notify failed (non-fatal): %s", e)

    return AnswerNowAcceptedOut(
        accepted=True,
        current_stage=round_.status,
        message=(
            f"Answer Now 已受理. 当前阶段 ({round_.status}) 完成后立刻合成部分结果."
        ),
    )


@router.patch("/{project_id}/scoring-config")
async def update_scoring_config(
    project_id: uuid.UUID,
    config: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新评分配置（斩杀线等）"""
    project = await _get_project_or_404(project_id, current_user.id, db)

    search_config = project.search_config or {}
    if "scoring_cutoff" in config:
        cutoff = float(config["scoring_cutoff"])
        if not (0 <= cutoff <= 10):
            raise HTTPException(status_code=400, detail="斩杀线必须在 0-10 之间")
        search_config["scoring_cutoff"] = cutoff

    await db.execute(
        update(Project).where(Project.id == project_id).values(search_config=search_config)
    )
    await db.commit()
    return {"status": "ok", "scoring_cutoff": search_config.get("scoring_cutoff")}


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
