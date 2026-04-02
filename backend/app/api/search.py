from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List
import uuid
import asyncio
import json
import os

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.search_round import SearchRound
from app.models.round_document import RoundDocument
from app.models.document import Document
from app.models.feedback import Feedback
from app.schemas.search import RoundStatusOut, DocumentOut, RoundResultsOut
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
            agent_score=rd.agent_score,
            agent_rationale=rd.agent_rationale,
            one_line_summary=rd.one_line_summary or doc.one_line_summary,
            below_cutoff=rd.below_cutoff or False,
            user_feedback=feedbacks.get(doc.id),
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

    from app.services.query_builder import get_max_rounds
    max_rounds = project.max_rounds or get_max_rounds(project.search_config)
    if project.current_round >= max_rounds:
        raise HTTPException(status_code=400, detail=f"已完成全部{max_rounds}轮检索，进入监控模式")

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
        elif current and current.status not in ("complete", "failed"):
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
    from app.services.core.llm_providers import LLMProviderManager
    from app.services.core.llm_config_store import load_llm_config
    from app.models.user_profile import UserProfile

    llm_manager = LLMProviderManager(default_ollama_host=settings.ollama_host)
    await load_llm_config(llm_manager, settings.redis_url)

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

    if settings.enable_scoring_agent:
        try:
            from app.harness.query_plan_agent import QueryPlanAgent
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
            query_plan = await qp_agent.plan(
                project_description=project.description,
                memory_text=memory_text or "",
                round_number=round_.round_number,
                max_rounds=project.max_rounds or get_max_rounds(project.search_config),
                tool_reliability=registry.get_reliability_report(),
                prev_source_stats=prev_stats,
            )
            if query_plan:
                _plan_source = "agent"
                # 从 agent 日志中取 rationale（存在 query_plan 的 metadata 或 agent 返回值中）
                _plan_rationale = getattr(query_plan, '_rationale', '') or ''
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[prepare] QueryPlanAgent 失败: %s", e)
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

    # 生成 per-source 关键词方案（展示所有可用源，Agent 推荐的默认开启）
    disabled_sources = {s.strip() for s in os.getenv("DISABLED_SOURCES", "").split(",") if s.strip()}

    from app.services.fetchers.international import ALL_FETCHERS
    all_available_sources = [sid for sid in ALL_FETCHERS.keys() if sid not in disabled_sources]
    agent_recommended = set(query_plan.sources)

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

    # 标记 Agent 未推荐的源为 disabled（用户仍可手动开启）
    for plan in keyword_result.source_plans:
        if plan.source_id not in agent_recommended:
            plan.enabled = False
            plan.notes = f"Agent 未推荐（可手动开启）" + (f"；{plan.notes}" if plan.notes else "")

    # 存入 Redis（TTL 10 分钟）
    import redis.asyncio as aioredis
    redis = aioredis.from_url(settings.redis_url)
    try:
        await redis.set(
            f"keyword_plan:{round_.id}",
            json.dumps(keyword_result.to_dict()),
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
    await db.refresh(round_)

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

    from app.workers.search_tasks import execute_round
    execute_round.delay(str(round_id))

    await db.refresh(round_)
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


@router.post("/{project_id}/documents/{document_id}/deep-dive")
async def trigger_deep_dive(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """触发单篇文献的深度分析（异步 Celery 任务）"""
    await _get_project_or_404(project_id, current_user.id, db)

    # 验证文档存在
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    from app.workers.deep_dive_tasks import execute_deep_dive
    task = execute_deep_dive.delay(str(document_id), str(project_id))

    return {"task_id": task.id, "status": "started", "document_id": str(document_id)}


@router.get("/{project_id}/documents/{document_id}/deep-dive")
async def get_deep_dive_result(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取深度分析结果（从 Redis 缓存读取）"""
    await _get_project_or_404(project_id, current_user.id, db)

    try:
        import redis.asyncio as aioredis
        from app.config import settings as _s
        r = aioredis.from_url(_s.redis_url)
        cached = await r.get(f"deep_dive:{document_id}")
        await r.close()
        if cached:
            return {"status": "completed", "analysis": json.loads(cached)}
    except Exception:
        pass

    return {"status": "not_found", "analysis": None}


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
