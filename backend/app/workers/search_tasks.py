"""
Celery 任务：执行单轮渐进式检索
流程：检索 → 保存文档 → 生成 AI 摘要 → chord callback 更新状态
"""
import asyncio
import logging
import uuid
from celery import chord, group
from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在 Celery worker（非 async）中运行协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.workers.search_tasks.execute_round", bind=True, max_retries=2)
def execute_round(self, round_id: str):
    """主任务：执行完整的一轮检索"""
    return _run_async(_execute_round_async(round_id))


async def _execute_round_async(round_id_str: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.search_round import SearchRound
    from app.models.project import Project
    from app.services.progressive_search import (
        mark_round_searching, mark_round_summarizing,
        mark_round_awaiting_feedback, save_round_documents,
    )
    from app.services.query_builder import build_query
    from app.services.search_engine import execute_search

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    round_id = uuid.UUID(round_id_str)

    async with session_factory() as db:
        try:
            # 1. 获取轮次和项目信息
            r = await db.execute(select(SearchRound).where(SearchRound.id == round_id))
            round_ = r.scalar_one_or_none()
            if not round_:
                return {"error": "Round not found"}

            p = await db.execute(select(Project).where(Project.id == round_.project_id))
            project = p.scalar_one_or_none()
            if not project:
                return {"error": "Project not found"}

            # 2. 标记为检索中
            await mark_round_searching(round_id, db)

            # [SSE] 通知前端：检索开始
            from app.services.event_bus import EventBus
            EventBus.publish_sync(round_id_str, "round_status", {"status": "searching", "progress": 0.1, "message": "检索中..."})

            # [Harness] ROUND_START hook
            try:
                from app.harness.hook_engine import HookEngine, HookPoint
                _hooks = HookEngine.get_instance()
                await _hooks.fire(HookPoint.ROUND_START, {
                    "round_id": round_id_str,
                    "round_number": round_.round_number,
                    "project_id": str(project.id),
                    "project_description": project.description[:200],
                })
            except Exception as _he:
                logger.warning("[Harness] ROUND_START hook error: %s", _he)

            # 3. 构建跨轮去重集合（排除已出现 + 用户标不相关的文档）
            from app.models.document import Document
            from app.models.round_document import RoundDocument
            from app.models.feedback import Feedback

            # 已出现在前序轮次的文档
            prev_docs_result = await db.execute(
                select(Document.source, Document.external_id)
                .join(RoundDocument, RoundDocument.document_id == Document.id)
                .join(SearchRound, SearchRound.id == RoundDocument.round_id)
                .where(SearchRound.project_id == project.id)
            )
            exclude_keys = {f"{row[0]}:{row[1]}" for row in prev_docs_result.all()}

            # 用户标为不相关的文档
            neg_result = await db.execute(
                select(Document.source, Document.external_id)
                .join(Feedback, Feedback.document_id == Document.id)
                .where(
                    Feedback.round_id.in_(
                        select(SearchRound.id).where(SearchRound.project_id == project.id)
                    ),
                    Feedback.relevance == -1,
                )
            )
            for row in neg_result.all():
                exclude_keys.add(f"{row[0]}:{row[1]}")

            # 4. 构建查询计划（加载用户配置的 LLM 用于中文描述翻译）
            from app.services.core.llm_providers import LLMProviderManager
            from app.services.core.llm_config_store import load_llm_config
            llm_manager = LLMProviderManager(default_ollama_host=settings.ollama_host)
            await load_llm_config(llm_manager, settings.redis_url)

            # 获取评分权重（从项目搜索配置）
            scoring_weights = None
            if project.search_config and "scoring_weights" in project.search_config:
                scoring_weights = project.search_config["scoring_weights"]

            # 加载用户画像 + 项目记忆
            from app.services.profile_service import get_or_create_profile
            profile = await get_or_create_profile(project.user_id, project.id, db)
            preferred_keywords = profile.preferred_keywords or []
            excluded_keywords = profile.excluded_keywords or []
            profile_embedding = getattr(profile, "positive_embedding", None) if round_.round_number > 1 else None

            # 加载上轮统计（Agent 决策参考）
            prev_stats = {}
            if round_.round_number > 1:
                from sqlalchemy import select as sa_select
                prev_round_q = await db.execute(
                    sa_select(SearchRound).where(
                        SearchRound.project_id == project.id,
                        SearchRound.round_number == round_.round_number - 1,
                    )
                )
                prev_round = prev_round_q.scalar_one_or_none()
                if prev_round and prev_round.source_stats:
                    prev_stats = prev_round.source_stats

            # ── Agent-First Query Planning ──
            # 优先让 Agent 直接从 description + memory 生成完整 QueryPlan
            # LLM 不可用时 fallback 到确定性 build_query()
            query_plan = None
            _plan_source = "fallback"

            if settings.enable_scoring_agent:
                try:
                    from app.harness.query_plan_agent import QueryPlanAgent
                    from app.harness.tool_registry import ToolRegistry
                    registry = ToolRegistry.get_instance()
                    from app.services.query_builder import get_max_rounds as _get_max_rounds

                    qp_agent = QueryPlanAgent(llm_manager=llm_manager)
                    query_plan = await qp_agent.plan(
                        project_description=project.description,
                        memory_text=profile.memory_text or "",
                        round_number=round_.round_number,
                        max_rounds=project.max_rounds or _get_max_rounds(project.search_config),
                        tool_reliability=registry.get_reliability_report(),
                        prev_source_stats=prev_stats,
                    )
                    if query_plan:
                        _plan_source = "agent"
                except Exception as e:
                    logger.warning("[QueryPlanAgent] Agent 规划失败，回退到 build_query: %s", e)
                    query_plan = None

            # Fallback: 确定性 build_query()（含 LLM 翻译 + 领域映射 + 画像注入）
            if query_plan is None:
                query_plan = await build_query(
                    project_description=project.description,
                    project_domain=project.domain,
                    round_number=round_.round_number,
                    preferred_keywords=preferred_keywords,
                    excluded_keywords=excluded_keywords,
                    llm_manager=llm_manager,
                    search_config=project.search_config,
                    project_domains=project.domains,
                    project_title=project.title,
                )

                # 旧路径：如果旧 Agent Planning 也开启，叠加到确定性 plan 上
                if settings.enable_agent_planning:
                    try:
                        from app.harness.agent_orchestrator import SearchStrategyAgent
                        from app.harness.tool_registry import ToolRegistry
                        registry = ToolRegistry.get_instance()
                        agent = SearchStrategyAgent(redis_url=settings.redis_url)
                        from app.services.query_builder import get_max_rounds as _get_max_rounds
                        old_plan = await agent.plan_round(
                            project_description=project.description,
                            round_number=round_.round_number,
                            max_rounds=project.max_rounds or _get_max_rounds(project.search_config),
                            profile_positive=preferred_keywords,
                            profile_negative=excluded_keywords,
                            tool_reliability=registry.get_reliability_report(),
                            prev_source_stats=prev_stats,
                            llm_manager=llm_manager,
                        )
                        if old_plan:
                            query_plan = old_plan.to_query_plan(
                                base_query=query_plan.base_query,
                                original_chinese_query=query_plan.original_chinese_query,
                                english_query_source=query_plan.english_query_source,
                                cn_query_source=query_plan.cn_query_source,
                                expanded_terms=query_plan.expanded_terms,
                                anchor_keywords=query_plan.anchor_keywords,
                                profile_injected_en=query_plan.profile_injected_en,
                                profile_injected_zh=query_plan.profile_injected_zh,
                                profile_query_extension=query_plan.profile_query_extension,
                                language_scope=query_plan.language_scope,
                            )
                            _plan_source = "legacy_agent"
                    except Exception as e:
                        logger.warning("[Harness] Legacy agent planning failed: %s", e)

            # [SSE] 通知前端规划结果
            EventBus.publish_sync(round_id_str, "agent_plan", {
                "plan_source": _plan_source,
                "base_query": query_plan.base_query[:100],
                "sources": query_plan.sources,
                "year_range": f"{query_plan.year_from}-{query_plan.year_to}",
            })

            # 4b. 将 QueryPlan 存入 search_queries（Dev View）
            from sqlalchemy import update as sql_update
            query_plan_info = {
                "base_query": query_plan.base_query,
                "expanded_terms": query_plan.expanded_terms,
                "exclude_terms": query_plan.exclude_terms,
                "year_from": query_plan.year_from,
                "year_to": query_plan.year_to,
                "language_scope": query_plan.language_scope,
                "sources_selected": query_plan.sources,
                "max_per_source": query_plan.max_results_per_source,
                "original_chinese_query": query_plan.original_chinese_query,
                "plan_source": _plan_source,
                # 保留旧字段（兼容 DevView 前端）
                "english_query_source": query_plan.english_query_source,
                "cn_query_source": query_plan.cn_query_source,
                "profile_injected_en": query_plan.profile_injected_en,
                "profile_injected_zh": query_plan.profile_injected_zh,
                "profile_query_extension": query_plan.profile_query_extension,
                "anchor_keywords": query_plan.anchor_keywords,
            }
            await db.execute(
                sql_update(SearchRound).where(SearchRound.id == round_id).values(
                    search_queries=query_plan_info
                )
            )
            await db.commit()

            # 4b. 加载用户确认的 per-source 关键词（如果有）
            per_source_queries = None
            dynamic_synonyms = None
            if settings.enable_per_source_keywords:
                try:
                    import redis.asyncio as aioredis
                    import json as _json
                    r = aioredis.from_url(settings.redis_url)
                    try:
                        raw = await r.get(f"keyword_plan:{round_id_str}")
                        if raw:
                            plan_data = _json.loads(raw)
                            if plan_data.get("confirmed"):
                                per_source_queries = {
                                    p["source_id"]: p["query"]
                                    for p in plan_data.get("source_plans", [])
                                    if p.get("enabled", True)
                                }
                                if per_source_queries:
                                    query_plan.sources = [
                                        s for s in query_plan.sources
                                        if s in per_source_queries
                                    ]
                                    logger.info(
                                        "[PerSourceKW] 使用用户确认的 %d 个源查询词",
                                        len(per_source_queries),
                                    )
                                # 用户对 QueryPlan 的修改覆盖 Agent 方案
                                if "base_query" in plan_data:
                                    query_plan.base_query = plan_data["base_query"]
                                    query_plan.expanded_terms = [
                                        w for w in plan_data["base_query"].split() if len(w) >= 2
                                    ]
                                    logger.info("[UserOverride] base_query → %s", query_plan.base_query[:60])
                                if "original_chinese_query" in plan_data:
                                    query_plan.original_chinese_query = plan_data["original_chinese_query"]
                                if "exclude_terms" in plan_data:
                                    query_plan.exclude_terms = plan_data["exclude_terms"]
                                if "year_from" in plan_data:
                                    query_plan.year_from = plan_data["year_from"]
                                if "year_to" in plan_data:
                                    query_plan.year_to = plan_data["year_to"]
                                if "max_per_source" in plan_data:
                                    query_plan.max_results_per_source = plan_data["max_per_source"]
                                if "language_scope" in plan_data:
                                    query_plan.language_scope = plan_data["language_scope"]
                            # 加载动态同义词（LLM 生成的项目特定同义词表）
                            dynamic_synonyms = plan_data.get("synonyms")
                            if dynamic_synonyms:
                                logger.info(
                                    "[PerSourceKW] 加载 %d 组动态同义词",
                                    len(dynamic_synonyms),
                                )
                    finally:
                        await r.close()
                except Exception as e:
                    logger.warning("[PerSourceKW] 加载确认关键词失败，使用默认: %s", e)

            # 5. 执行检索 — Agent Search Loop（自适应多轮迭代）或单次执行
            from app.harness.search_loop import AgentSearchLoop
            search_loop = AgentSearchLoop()
            loop_result = await search_loop.run(
                query_plan,
                exclude_doc_keys=exclude_keys if exclude_keys else None,
                scoring_weights=scoring_weights,
                profile_embedding=profile_embedding,
                llm_manager=llm_manager if settings.enable_agent_planning else None,
                per_source_queries=per_source_queries,
                dynamic_synonyms=dynamic_synonyms,
            )
            selected_docs = loop_result.all_docs
            total_candidates = loop_result.total_candidates
            source_stats = loop_result.source_stats
            if len(loop_result.iterations) > 1:
                logger.info("[Harness] Search Loop: %s", loop_result.loop_rationale)

            # [Harness] POST_SEARCH hook
            try:
                await _hooks.fire(HookPoint.POST_SEARCH, {
                    "round_id": round_id_str,
                    "total_candidates": total_candidates,
                    "selected_count": len(selected_docs),
                    "source_stats": source_stats,
                })
            except Exception as _he:
                logger.warning("[Harness] POST_SEARCH hook error: %s", _he)

            # 5b. LLM Reranking（可选，通过 search_config.enable_llm_rerank 开关）
            if selected_docs and project.search_config and project.search_config.get("enable_llm_rerank"):
                from app.services.llm_reranker import llm_rerank
                selected_docs = await llm_rerank(
                    docs=selected_docs,
                    project_description=project.description,
                    llm_manager=llm_manager,
                )

            # 5c. Scoring Agent — LLM 逐篇评分（feature-flagged）
            if selected_docs and settings.enable_scoring_agent:
                try:
                    from app.harness.scoring_agent import ScoringAgent

                    # 触发 PRE_SCORING hook
                    try:
                        await _hooks.fire(HookPoint.PRE_SCORING, {
                            "round_id": round_id_str,
                            "doc_count": len(selected_docs),
                        })
                    except Exception as _he:
                        logger.warning("[Harness] PRE_SCORING hook error: %s", _he)

                    # 加载用户记忆（Memory Agent 写入的结构化记忆）
                    _user_memory = ""
                    if profile.memory_text:
                        _user_memory = profile.memory_text

                    # 获取斩杀线
                    _cutoff = settings.scoring_cutoff_default
                    if project.search_config and "scoring_cutoff" in project.search_config:
                        _cutoff = float(project.search_config["scoring_cutoff"])

                    EventBus.publish_sync(round_id_str, "round_status", {
                        "status": "scoring", "progress": 0.45,
                        "message": f"AI 正在评估 {len(selected_docs)} 篇文献相关性...",
                    })

                    scoring_agent = ScoringAgent(llm_manager=llm_manager)
                    _scoring_desc = f"【{project.title}】{project.description}" if project.title else project.description
                    above_cutoff, below_cutoff = await scoring_agent.score_all(
                        docs=selected_docs,
                        project_description=_scoring_desc,
                        cutoff=_cutoff,
                        user_memory=_user_memory,
                    )

                    # 合并：above 在前，below 在后（都保存，但标记 below_cutoff）
                    selected_docs = above_cutoff + below_cutoff

                    # 触发 POST_SCORING hook
                    try:
                        await _hooks.fire(HookPoint.POST_SCORING, {
                            "round_id": round_id_str,
                            "above_cutoff": len(above_cutoff),
                            "below_cutoff": len(below_cutoff),
                            "cutoff": _cutoff,
                        })
                    except Exception as _he:
                        logger.warning("[Harness] POST_SCORING hook error: %s", _he)

                    EventBus.publish_sync(round_id_str, "scoring_complete", {
                        "above_cutoff": len(above_cutoff),
                        "below_cutoff": len(below_cutoff),
                        "cutoff": _cutoff,
                    })

                    logger.info(
                        "[ScoringAgent] Round %s: %d above / %d below cutoff (%.1f)",
                        round_id_str[:8], len(above_cutoff), len(below_cutoff), _cutoff,
                    )
                except Exception as e:
                    logger.warning("[ScoringAgent] 评分失败，使用传统分数: %s", e)

            # [SSE] 通知前端：检索完成
            EventBus.publish_sync(round_id_str, "round_status", {"status": "saving", "progress": 0.5, "message": f"检索完成，{len(selected_docs)}篇文献"})

            # 6. 若无文档则直接进入等待反馈（也保存 source_stats）
            if not selected_docs:
                from sqlalchemy import update as sql_update
                await db.execute(
                    sql_update(SearchRound).where(SearchRound.id == round_id).values(
                        source_stats=source_stats,
                        total_candidates=total_candidates,
                    )
                )
                await db.commit()
                await mark_round_awaiting_feedback(round_id, db)
                return {"round_id": round_id_str, "selected": 0, "total": total_candidates}

            # 7. 保存文档到数据库
            await save_round_documents(round_id, selected_docs, db)

            # 8. 标记为摘要生成中（含数据源统计）
            await mark_round_summarizing(round_id, total_candidates, len(selected_docs), db, source_stats=source_stats)

            # [SSE] 通知前端：摘要生成开始 + 逐篇文献到达
            EventBus.publish_sync(round_id_str, "round_status", {"status": "summarizing", "progress": 0.6, "message": "正在生成AI摘要..."})
            for doc in selected_docs:
                EventBus.publish_sync(round_id_str, "doc_arrived", {
                    "external_id": str(doc.get("external_id", "")),
                    "source": doc.get("source"),
                    "title": doc.get("title", ""),
                    "doc_type": doc.get("doc_type", "paper"),
                    "has_abstract": bool(doc.get("abstract")),
                })

            # 8. 使用 Celery chord：所有摘要子任务完成后触发 finalize 回调
            summary_tasks = []
            for doc in selected_docs:
                source = doc.get("source")
                external_id = str(doc.get("external_id", ""))
                summary_tasks.append(
                    generate_summary_for_doc.s(
                        round_id_str=round_id_str,
                        source=source,
                        external_id=external_id,
                        project_description=project.description,
                    )
                )

            # [Harness] PRE_SUMMARIZE hook
            try:
                await _hooks.fire(HookPoint.PRE_SUMMARIZE, {
                    "round_id": round_id_str,
                    "doc_count": len(selected_docs),
                })
            except Exception as _he:
                logger.warning("[Harness] PRE_SUMMARIZE hook error: %s", _he)

            # [Harness] Multi-Agent Coordinator — run Quality + Profile agents in parallel with summaries
            try:
                from app.harness.coordinator import QualityAgent, ProfilePreAnalyzer, AutoSkillTrigger

                quality_agent = QualityAgent()
                profile_agent = ProfilePreAnalyzer()
                auto_skills = AutoSkillTrigger()

                # Run coordinator agents in parallel (non-blocking, results stored in round metadata)
                coord_results = await asyncio.gather(
                    quality_agent.evaluate(selected_docs, query_plan_info, project.description, llm_manager),
                    profile_agent.pre_analyze(selected_docs, project.description, llm_manager),
                    auto_skills.evaluate_triggers(selected_docs, round_.round_number, str(project.id)),
                    return_exceptions=True,
                )

                # Store coordinator results in round metadata
                coord_meta = {}
                for i, result in enumerate(coord_results):
                    if isinstance(result, dict):
                        label = ["quality", "profile_pre", "auto_skills"][i]
                        coord_meta[label] = result

                if coord_meta:
                    from sqlalchemy import update as sql_update2
                    await db.execute(
                        sql_update2(SearchRound).where(SearchRound.id == round_id).values(
                            progress_message=f"搜索完成，{len(selected_docs)}篇文献，正在生成摘要... "
                                             f"[Quality: {coord_meta.get('quality', {}).get('metrics', {}).get('abstract_rate', '?')}% 有摘要]"
                        )
                    )
                    await db.commit()
                    logger.info("[Harness] Coordinator results: quality=%s, pre_profile=%d keywords, auto_skills=%d",
                                coord_meta.get("quality", {}).get("metrics", {}).get("abstract_rate", "?"),
                                len(coord_meta.get("profile_pre", {}).get("novel_keywords", [])),
                                len(coord_meta.get("auto_skills", [])))
            except Exception as e:
                logger.warning("[Harness] Coordinator failed (non-fatal): %s", e)

            callback = finalize_round_after_summaries.si(round_id_str=round_id_str)
            chord(group(summary_tasks))(callback)

            return {"round_id": round_id_str, "selected": len(selected_docs), "total": total_candidates}

        except Exception as e:
            logger.error("[execute_round] 错误: %s", e, exc_info=True)
            # 标记失败
            from sqlalchemy import update
            from app.models.search_round import SearchRound
            await db.execute(
                update(SearchRound).where(SearchRound.id == round_id).values(
                    status="failed", progress_message=str(e)[:200]
                )
            )
            await db.commit()
            raise

    await engine.dispose()


@celery_app.task(name="app.workers.search_tasks.generate_summary_for_doc", bind=True, max_retries=1)
def generate_summary_for_doc(self, round_id_str: str, source: str, external_id: str, project_description: str):
    """为单篇文档生成 AI 摘要。失败时不抛异常，确保 chord 不中断。"""
    try:
        return _run_async(_generate_summary_async(round_id_str, source, external_id, project_description))
    except Exception as e:
        # 捕获所有异常，返回错误信息而非抛出，避免 chord 因单个子任务失败而中断
        logger.error("[generate_summary_for_doc] 失败 source=%s external_id=%s: %s", source, external_id, e)
        return {"status": "failed", "error": str(e)}


async def _generate_summary_async(round_id_str: str, source: str, external_id: str, project_description: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, update
    from app.config import settings
    from app.models.document import Document
    from app.services.core.llm_providers import LLMProviderManager
    from app.services.llm_summarizer import LLMSummarizer

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            r = await db.execute(
                select(Document).where(Document.source == source, Document.external_id == external_id)
            )
            doc = r.scalar_one_or_none()
            if not doc:
                return {"status": "skipped", "reason": "document not found"}

            # 从 Redis 加载用户配置的 LLM（包含 DeepSeek/OpenAI 等）
            from app.services.core.llm_config_store import load_llm_config
            llm_manager = LLMProviderManager(default_ollama_host=settings.ollama_host)
            await load_llm_config(llm_manager, settings.redis_url)
            summarizer = LLMSummarizer(llm_manager)

            doc_dict = {
                "title": doc.title,
                "abstract": doc.abstract,
                "fulltext_text": doc.fulltext_text,
            }

            summary, key_points, relevance_reason, summary_source = await summarizer.generate_summary(
                doc=doc_dict,
                project_description=project_description,
                use_fulltext=bool(doc.fulltext_text),
            )

            if summary:
                await db.execute(
                    update(Document).where(Document.id == doc.id).values(
                        ai_summary=summary,
                        ai_key_points=key_points or [],
                        ai_relevance_reason=relevance_reason,
                        ai_summary_source=summary_source,
                    )
                )
                await db.commit()

                # [SSE] 通知前端：单篇摘要完成
                from app.services.event_bus import EventBus
                EventBus.publish_sync(round_id_str, "summary_ready", {
                    "external_id": external_id,
                    "source": source,
                    "summary_preview": summary[:200] if summary else None,
                    "key_points": key_points[:3] if key_points else [],
                })

                return {"status": "ok", "source": source, "external_id": external_id}
            else:
                return {"status": "no_summary", "source": source, "external_id": external_id}
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.search_tasks.finalize_round_after_summaries")
def finalize_round_after_summaries(round_id_str: str):
    """Chord 回调：所有摘要子任务完成后，将轮次状态转为 awaiting_feedback"""
    return _run_async(_finalize_round_async(round_id_str))


async def _finalize_round_async(round_id_str: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, update, func
    from app.config import settings
    from app.models.search_round import SearchRound
    from app.models.round_document import RoundDocument
    from app.models.document import Document

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    round_id = uuid.UUID(round_id_str)

    try:
        async with session_factory() as db:
            r = await db.execute(select(SearchRound).where(SearchRound.id == round_id))
            round_ = r.scalar_one_or_none()
            if not round_ or round_.status != "summarizing":
                return {"status": "skipped", "reason": f"round status is {round_.status if round_ else 'not found'}"}

            # 统计摘要完成情况（仅用于日志，不影响状态转移）
            total = await db.execute(
                select(func.count()).select_from(RoundDocument).where(RoundDocument.round_id == round_id)
            )
            total_count = total.scalar()

            done = await db.execute(
                select(func.count()).select_from(RoundDocument)
                .join(Document, RoundDocument.document_id == Document.id)
                .where(
                    RoundDocument.round_id == round_id,
                    Document.ai_summary.isnot(None),
                )
            )
            done_count = done.scalar()

            logger.info("[finalize_round] round=%s 摘要完成 %d/%d", round_id_str, done_count, total_count)

            # 无论摘要是否全部成功，都转入 awaiting_feedback（用户可以看到哪些有摘要哪些没有）
            await db.execute(
                update(SearchRound).where(SearchRound.id == round_id).values(
                    status="awaiting_feedback",
                    progress=1.0,
                    progress_message=f"摘要生成完毕（{done_count}/{total_count}篇成功），请评分",
                )
            )
            await db.commit()

            # [SSE] 通知前端：轮次完成
            from app.services.event_bus import EventBus
            EventBus.publish_sync(round_id_str, "round_complete", {
                "total": total_count,
                "summaries_done": done_count,
            })

            return {"status": "ok", "done": done_count, "total": total_count}
    finally:
        await engine.dispose()
