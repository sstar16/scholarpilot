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

            # 加载用户画像（第2轮起将 preferred_keywords 注入扩展词）
            from app.services.profile_service import get_or_create_profile
            profile = await get_or_create_profile(project.user_id, project.id, db)
            preferred_keywords = profile.preferred_keywords or []
            excluded_keywords = profile.excluded_keywords or []
            # 画像向量（第2轮起生效；首轮反馈完成后由 embedding_tasks 异步生成）
            # 用 getattr 避免 pgvector 未安装时 AttributeError
            profile_embedding = getattr(profile, "positive_embedding", None) if round_.round_number > 1 else None

            query_plan = await build_query(
                project_description=project.description,
                project_domain=project.domain,
                round_number=round_.round_number,
                preferred_keywords=preferred_keywords,
                excluded_keywords=excluded_keywords,
                llm_manager=llm_manager,
                search_config=project.search_config,
                project_domains=project.domains,
            )

            # 4b. 将 QueryPlan 核心信息存入 search_queries（供 Dev View 使用）
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
                "profile_keywords": preferred_keywords[:10] if round_.round_number > 1 else [],
                "profile_excluded": excluded_keywords[:3] if round_.round_number > 1 else [],
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

            # 5. 执行并行检索（传入跨轮去重集合和评分权重）
            selected_docs, total_candidates, source_stats = await execute_search(
                query_plan,
                exclude_doc_keys=exclude_keys if exclude_keys else None,
                scoring_weights=scoring_weights,
                profile_embedding=profile_embedding,
            )

            # 5b. LLM Reranking（可选，通过 search_config.enable_llm_rerank 开关）
            if selected_docs and project.search_config and project.search_config.get("enable_llm_rerank"):
                from app.services.llm_reranker import llm_rerank
                selected_docs = await llm_rerank(
                    docs=selected_docs,
                    project_description=project.description,
                    llm_manager=llm_manager,
                )

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
            return {"status": "ok", "done": done_count, "total": total_count}
    finally:
        await engine.dispose()
