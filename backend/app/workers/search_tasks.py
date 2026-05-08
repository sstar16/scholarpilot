"""
Celery 任务：执行单轮渐进式检索

主链路 ``execute_round`` 现在仅是 Pipeline DAG 的入口：所有相位在
``app/harness/pipeline/phases/`` 下分文件实现，由 ``PhaseRunner`` 拓扑调度。
摘要 fan-out（generate_summary_for_doc）、chord 回调（finalize_round_after_summaries）
与 fire-and-forget Coordinator 仍保留为独立 Celery 任务，由 DispatchSummariesPhase
派发。
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
    """主任务：执行完整的一轮检索（通过 PhaseRunner 调度）。"""
    return _run_async(_execute_round_async(round_id))


async def _execute_round_async(round_id_str: str):
    """Run the round through the Pipeline DAG.

    Returns a dict with one of these shapes:
        {round_id, selected, total}                — happy path
        {round_id, partial: True, stage}           — Answer Now triggered
        {round_id, selected: 0, total}             — fetch returned 0 docs
        {error: "..."}                             — round/project not found
    """
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import redis.asyncio as aioredis
    from sqlalchemy import update

    from app.config import settings
    from app.harness.pipeline import PhaseAborted, PhaseRunner, RoundContext
    from app.harness.pipeline.phases import (
        ApplySearchModePhase,
        BuildDedupPhase,
        DispatchSummariesPhase,
        FetchPhase,
        LoadConfirmedKeywordsPhase,
        LoadMemoryPhase,
        LoadRoundPhase,
        PlanQueryPhase,
        RerankPhase,
        SaveDocsPhase,
        ScorePhase,
    )
    from app.models.search_round import SearchRound
    from app.services.core.llm_config_store import get_llm_manager

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    redis_client = aioredis.from_url(settings.redis_url)

    try:
        async with session_factory() as db:
            ctx = RoundContext(
                round_id=round_id_str,
                db=db,
                redis=redis_client,
                llm_manager=await get_llm_manager(),
            )
            runner = PhaseRunner([
                LoadRoundPhase(),
                BuildDedupPhase(),
                LoadMemoryPhase(),
                PlanQueryPhase(),
                LoadConfirmedKeywordsPhase(),
                ApplySearchModePhase(),
                FetchPhase(),
                RerankPhase(),
                ScorePhase(),
                SaveDocsPhase(),
                DispatchSummariesPhase(),
            ])
            try:
                await runner.run(ctx)
                disp = ctx.get("dispatch_summaries")
                return {
                    "round_id": round_id_str,
                    "selected": disp["selected"],
                    "total": disp["total"],
                }
            except PhaseAborted as e:
                if e.reason == "user_requested_partial":
                    return {
                        "round_id": round_id_str,
                        "partial": True,
                        "stage": e.payload.get("stage"),
                    }
                if e.reason == "zero_results":
                    return {
                        "round_id": round_id_str,
                        "selected": e.payload.get("selected", 0),
                        "total": e.payload.get("total", 0),
                    }
                if e.reason in ("round_not_found", "project_not_found"):
                    return e.payload or {"error": e.reason}
                return {"round_id": round_id_str, "aborted": e.reason, **e.payload}
            except Exception as e:
                logger.error("[execute_round] 错误: %s", e, exc_info=True)
                await db.execute(
                    update(SearchRound)
                    .where(SearchRound.id == uuid.UUID(round_id_str))
                    .values(status="failed", progress_message=str(e)[:200])
                )
                await db.commit()
                raise
    finally:
        try:
            await redis_client.close()
        except Exception:
            pass
        await engine.dispose()


@celery_app.task(name="app.workers.search_tasks.generate_summary_for_doc", bind=True, max_retries=1)
def generate_summary_for_doc(self, round_id_str: str, source: str, external_id: str, project_description: str, session_id: str = None):
    """为单篇文档生成 AI 摘要。失败时不抛异常，确保 chord 不中断。"""
    try:
        return _run_async(_generate_summary_async(round_id_str, source, external_id, project_description, session_id))
    except Exception as e:
        # 捕获所有异常，返回错误信息而非抛出，避免 chord 因单个子任务失败而中断
        logger.error("[generate_summary_for_doc] 失败 source=%s external_id=%s: %s", source, external_id, e)
        return {"status": "failed", "error": str(e)}


async def _generate_summary_async(round_id_str: str, source: str, external_id: str, project_description: str, session_id: str = None):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, update, func
    from app.config import settings
    from app.models.document import Document
    from app.models.round_document import RoundDocument
    from app.services.llm_summarizer import LLMSummarizer

    # 设置 LLM 上下文用于工作台 token 追踪
    from app.services.core.llm_context import set_llm_context, LLMContext
    set_llm_context(LLMContext(session_id=session_id, round_id=round_id_str, agent_name="Summarizer"))

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

            # 从缓存获取用户配置的 LLM
            from app.services.core.llm_config_store import get_llm_manager
            llm_manager = await get_llm_manager()
            summarizer = LLMSummarizer(llm_manager)

            doc_dict = {
                "title": doc.title,
                "abstract": doc.abstract,
                "fulltext_text": doc.fulltext_text,
            }

            llm_result = await summarizer.generate_summary(
                doc=doc_dict,
                project_description=project_description,
                use_fulltext=bool(doc.fulltext_text),
            )
            summary = llm_result["summary"]
            key_points = llm_result["key_points"]
            relevance_reason = llm_result["relevance_reason"]
            summary_source = llm_result["summary_source"]

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

                # [Harness] B3: POST_SUMMARIZE hook —— 单篇摘要完成后触发统计/索引
                try:
                    from app.harness.hook_engine import HookEngine, HookPoint
                    await HookEngine.get_instance().fire(HookPoint.POST_SUMMARIZE, {
                        "round_id": round_id_str,
                        "document_id": str(doc.id),
                        "source": source,
                        "external_id": external_id,
                        "has_fulltext": bool(doc.fulltext_text),
                        "summary_source": summary_source,
                    })
                except Exception as _he:
                    logger.warning("[Harness] POST_SUMMARIZE hook error: %s", _he)

                # [S1 NEW] 写 concept_tags + markdown workspace
                try:
                    from sqlalchemy import select as _select
                    from app.models.search_round import SearchRound
                    from app.models.document_classification import DocumentClassification
                    from app.services.literature_writer import LiteratureWriter
                    from app.harness.file_tools.registry import tool_registry

                    r_q = await db.execute(
                        _select(SearchRound.project_id).where(
                            SearchRound.id == uuid.UUID(round_id_str)
                        )
                    )
                    project_id = r_q.scalar_one_or_none()

                    bucket = None
                    if project_id is not None:
                        b_q = await db.execute(
                            _select(DocumentClassification.bucket).where(
                                DocumentClassification.project_id == project_id,
                                DocumentClassification.document_id == doc.id,
                            )
                        )
                        bucket = b_q.scalar_one_or_none()

                    # 提取 concept_tags: 仅 name 列表, 去重, 截 20
                    concept_tags: list[str] = []
                    for c in (llm_result.get("concepts") or []):
                        if isinstance(c, dict) and c.get("name"):
                            n = str(c["name"]).strip()[:60]
                            if n and n not in concept_tags:
                                concept_tags.append(n)
                        if len(concept_tags) >= 20:
                            break
                    if concept_tags:
                        await db.execute(
                            update(Document).where(Document.id == doc.id).values(
                                concept_tags=concept_tags,
                            )
                        )
                        await db.commit()

                    # 写 markdown workspace
                    if project_id is not None:
                        lw_doc_dict = {
                            "id": str(doc.id),
                            "title": doc.title,
                            "title_zh": getattr(doc, "title_zh", None),
                            "authors": doc.authors,
                            "source": doc.source,
                            "external_id": doc.external_id,
                            "doi": doc.doi,
                            "journal": doc.journal,
                            "publication_date": str(doc.publication_date) if doc.publication_date else None,
                            "url": doc.url,
                            "pdf_url": doc.pdf_url,
                            "abstract": doc.abstract,
                            "one_line_summary": doc.one_line_summary,
                            "quality_score": doc.quality_score,
                            "ai_summary": summary,
                            "ai_key_points": key_points or [],
                            "ai_summary_source": summary_source,
                            "fulltext_text": bool(doc.fulltext_text),
                            "round_id": round_id_str,
                        }
                        writer = LiteratureWriter(str(project_id), tool_registry())
                        await writer.persist(lw_doc_dict, bucket, llm_result)
                except Exception as _lw_e:
                    logger.error(
                        "[LibWriter] persist failed round=%s source=%s external_id=%s: %s",
                        round_id_str[:8], source, external_id, _lw_e,
                    )
                    # 不回滚: 主 summary 已成功 commit, 下次 rebuild 会补 md

                # [SSE] 通知前端：单篇摘要完成
                from app.services.event_bus import EventBus
                EventBus.publish_sync(round_id_str, "summary_ready", {
                    "external_id": external_id,
                    "source": source,
                    "summary_preview": summary[:200] if summary else None,
                    "key_points": key_points[:3] if key_points else [],
                })

                # 同步推送 round_status：按当前已完成摘要数 / 总数 计算 0.62 → 0.98 区间。
                # 2026-04-25 P1 优化：
                #   - 单次 SQL 同时取 total + done（合并 2 次 COUNT 为 1 次）
                #   - 节流广播：done_n == 1 / 末篇 / 每 3 篇 才推送，避免 N 次 Redis pub/sub
                try:
                    from sqlalchemy import case as _sql_case
                    import uuid as _uuid
                    _rid = _uuid.UUID(round_id_str)
                    combined_q = await db.execute(
                        select(
                            func.count().label("total"),
                            func.coalesce(
                                func.sum(_sql_case((Document.ai_summary.isnot(None), 1), else_=0)),
                                0,
                            ).label("done"),
                        )
                        .select_from(RoundDocument)
                        .outerjoin(Document, RoundDocument.document_id == Document.id)
                        .where(RoundDocument.round_id == _rid)
                    )
                    row = combined_q.first()
                    total_n = int(row.total or 0)
                    done_n = int(row.done or 0)
                    should_publish = (
                        total_n > 0 and (
                            done_n == 1
                            or done_n == total_n
                            or done_n % 3 == 0
                        )
                    )
                    if should_publish:
                        ratio = max(0.0, min(1.0, done_n / total_n))
                        prog = round(0.62 + ratio * 0.36, 3)
                        EventBus.publish_sync(round_id_str, "round_status", {
                            "status": "summarizing",
                            "progress": prog,
                            "message": f"已生成 {done_n}/{total_n} 篇 AI 摘要",
                        })
                except Exception:
                    pass  # 进度推送失败不影响摘要本身

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

            # [S1] 重建 literature/_index.md + slug_map.json (在状态转 awaiting_feedback 之前)
            try:
                from app.services.literature_writer import LiteratureWriter
                from app.harness.file_tools.registry import tool_registry

                writer = LiteratureWriter(str(round_.project_id), tool_registry())
                await writer.rebuild_index()
            except Exception as _lw_e:
                logger.error(
                    "[LibWriter] index rebuild failed round=%s: %s",
                    round_id_str[:8], _lw_e,
                )

            # 无论摘要是否全部成功，都转入 awaiting_feedback（用户可以看到哪些有摘要哪些没有）
            # M2: 同时设置 expires_at = NOW + 7d，让 cleanup_expired_round_cache 在 7 天后清掉这条 round
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            await db.execute(
                update(SearchRound).where(SearchRound.id == round_id).values(
                    status="awaiting_feedback",
                    progress=1.0,
                    progress_message=f"摘要生成完毕（{done_count}/{total_count}篇成功），请评分",
                    expires_at=_dt.now(_tz.utc) + _td(days=7),
                )
            )
            await db.commit()

            # [SSE] 通知前端：轮次完成
            from app.services.event_bus import EventBus
            EventBus.publish_sync(round_id_str, "round_complete", {
                "total": total_count,
                "summaries_done": done_count,
            })

            # 注入富消息：本轮检索结果卡片
            try:
                from app.services.conversation_inject import inject_rich_message
                # 收集本轮的 doc_ids 与基本元数据
                docs_q = await db.execute(
                    select(Document.id, Document.title, Document.source, Document.ai_summary)
                    .join(RoundDocument, RoundDocument.document_id == Document.id)
                    .where(RoundDocument.round_id == round_id)
                    .limit(30)
                )
                preview_docs = [
                    {
                        "id": str(row[0]),
                        "title": (row[1] or "")[:200],
                        "source": row[2],
                        "has_summary": bool(row[3]),
                    }
                    for row in docs_q.all()
                ]
                await inject_rich_message(
                    db,
                    project_id=round_.project_id,
                    rich_type="round_results",
                    content=f"第 {round_.round_number} 轮检索完成，共找到 {total_count} 篇文献",
                    rich_data={
                        "round_id": round_id_str,
                        "round_number": round_.round_number,
                        "total": total_count,
                        "summaries_done": done_count,
                        "docs": preview_docs,
                    },
                )
            except Exception as _inj_err:
                logger.warning("[finalize_round_after_summaries] inject round_results failed: %s", _inj_err)

            return {"status": "ok", "done": done_count, "total": total_count}
    finally:
        await engine.dispose()


# ──────────────────────── Coordinator (fire-and-forget) ────────────────────────
# 2026-04-25 P1 优化：原本主流程 await asyncio.gather(quality, profile, auto_skills)
# 阻塞 chord 派发 3-10s。改成独立 Celery 任务异步跑，结果只用于日志/round metadata，
# 不影响摘要主链路开始时间。

@celery_app.task(name="app.workers.search_tasks.run_coordinator_async", bind=True, max_retries=1)
def run_coordinator_async(self, round_id_str: str):
    """异步执行 QualityAgent + ProfilePreAnalyzer + AutoSkillTrigger，fire-and-forget。"""
    try:
        return _run_async(_coordinator_async(round_id_str))
    except Exception as e:
        logger.error("[Coordinator/async] 失败 round=%s: %s", round_id_str[:8], e)
        return {"status": "failed", "error": str(e)}


async def _coordinator_async(round_id_str: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.search_round import SearchRound
    from app.models.project import Project
    from app.models.document import Document
    from app.models.round_document import RoundDocument
    from app.harness.coordinator import QualityAgent, ProfilePreAnalyzer, AutoSkillTrigger
    from app.services.core.llm_config_store import get_llm_manager

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    round_id = uuid.UUID(round_id_str)

    try:
        async with session_factory() as db:
            r = await db.execute(select(SearchRound).where(SearchRound.id == round_id))
            round_ = r.scalar_one_or_none()
            if not round_:
                return {"status": "round_not_found"}
            p = await db.execute(select(Project).where(Project.id == round_.project_id))
            project = p.scalar_one_or_none()
            if not project:
                return {"status": "project_not_found"}

            # 加载本轮文献（dict 化，coordinator agent 接受 List[Dict]）
            docs_q = await db.execute(
                select(Document)
                .join(RoundDocument, RoundDocument.document_id == Document.id)
                .where(RoundDocument.round_id == round_id)
            )
            doc_objs = docs_q.scalars().all()
            docs = [
                {
                    "title": d.title,
                    "abstract": d.abstract,
                    "doi": d.doi,
                    "source": d.source,
                    "citation_count": d.citation_count or 0,
                    "ai_key_points": d.ai_key_points or [],
                    "_db_id": str(d.id),
                }
                for d in doc_objs
            ]
            if not docs:
                return {"status": "no_docs"}

            llm_manager = await get_llm_manager()
            quality_agent = QualityAgent()
            profile_agent = ProfilePreAnalyzer()
            auto_skills = AutoSkillTrigger()

            coord_results = await asyncio.gather(
                quality_agent.evaluate(docs, round_.search_queries or {}, project.description, llm_manager),
                profile_agent.pre_analyze(docs, project.description, llm_manager),
                auto_skills.evaluate_triggers(docs, round_.round_number, str(project.id)),
                return_exceptions=True,
            )

            coord_meta = {}
            labels = ["quality", "profile_pre", "auto_skills"]
            for i, result in enumerate(coord_results):
                if isinstance(result, dict):
                    coord_meta[labels[i]] = result

            logger.info(
                "[Coordinator/async] round=%s quality=%s, novel_kw=%d, auto_skills=%d",
                round_id_str[:8],
                coord_meta.get("quality", {}).get("metrics", {}).get("abstract_rate", "?"),
                len(coord_meta.get("profile_pre", {}).get("novel_keywords", [])),
                len(coord_meta.get("auto_skills", [])),
            )
            return {"status": "ok", "labels": list(coord_meta.keys())}
    finally:
        await engine.dispose()
