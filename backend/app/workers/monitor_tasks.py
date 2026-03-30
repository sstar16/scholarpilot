"""
Celery 定时任务：每日监控
每天早6点自动检索，对照用户画像打分，高相关文档生成摘要后存入 monitor_results
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.workers.monitor_tasks.run_daily_monitors")
def run_daily_monitors():
    """触发所有活跃的每日监控任务"""
    return _run_async(_find_and_dispatch_monitors())


async def _find_and_dispatch_monitors():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.monitor_job import MonitorJob

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        result = await db.execute(
            select(MonitorJob).where(MonitorJob.is_active == True, MonitorJob.schedule == "daily")
        )
        jobs = result.scalars().all()
        job_ids = [str(j.id) for j in jobs]

    await engine.dispose()

    for job_id in job_ids:
        run_single_monitor.delay(job_id)

    return {"triggered": len(job_ids)}


@celery_app.task(name="app.workers.monitor_tasks.run_single_monitor", bind=True, max_retries=1)
def run_single_monitor(self, job_id: str):
    """
    执行单个监控任务：
    1. 检索近7天新内容
    2. 与已见文档去重
    3. 相关度 > 0.5 的文档生成摘要
    4. 写入 monitor_results
    5. 更新 last_run_at / next_run_at
    """
    try:
        return _run_async(_run_monitor_async(job_id))
    except Exception as e:
        logger.error("[Monitor] 任务失败 job=%s: %s", job_id, e, exc_info=True)
        raise self.retry(exc=e, countdown=300)


async def _run_monitor_async(job_id_str: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, update
    from app.config import settings
    from app.models.monitor_job import MonitorJob, MonitorResult
    from app.models.project import Project
    from app.models.document import Document
    from app.models.round_document import RoundDocument
    from app.models.search_round import SearchRound
    from app.models.user_profile import UserProfile
    from app.services.query_builder import QueryPlan, _extract_core_query, _select_sources
    from app.services.search_engine import execute_search
    from app.services.relevance_engine import keyword_score
    from app.services.progressive_search import save_round_documents

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    job_id = uuid.UUID(job_id_str)
    now = datetime.now(timezone.utc)

    try:
        async with session_factory() as db:
            # 1. 加载监控任务和关联项目
            r = await db.execute(select(MonitorJob).where(MonitorJob.id == job_id))
            job = r.scalar_one_or_none()
            if not job or not job.is_active:
                return {"status": "skipped", "reason": "job not found or inactive"}

            p = await db.execute(select(Project).where(Project.id == job.project_id))
            project = p.scalar_one_or_none()
            if not project:
                return {"status": "skipped", "reason": "project not found"}

            search_config = job.search_config or {}
            sources = search_config.get("sources") or ["pubmed", "openalex", "semantic_scholar", "arxiv"]

            # 2. 构建查询计划（近7天，重叠14天防漏）
            from datetime import datetime as dt
            base_query = _extract_core_query(project.description)
            year_from_date = now - timedelta(days=14)

            # 加载用户画像关键词
            profile_r = await db.execute(
                select(UserProfile).where(
                    UserProfile.user_id == job.user_id,
                    UserProfile.project_id == job.project_id,
                )
            )
            profile = profile_r.scalar_one_or_none()
            preferred_kw = profile.preferred_keywords[:5] if profile and profile.preferred_keywords else []
            excluded_kw = profile.excluded_keywords[:3] if profile and profile.excluded_keywords else []

            query_plan = QueryPlan(
                base_query=base_query,
                expanded_terms=[base_query] + preferred_kw,
                exclude_terms=excluded_kw,
                year_from=year_from_date.year,
                year_to=now.year,
                sources=sources,
                max_results_per_source=20,
                language_scope="global",
            )

            # 3. 执行检索
            all_docs, total, _stats = await execute_search(query_plan)
            if not all_docs:
                await _update_job_timestamps(job_id, now, db)
                return {"status": "ok", "new_docs": 0, "total_candidates": total}

            # 4. 去重：排除本项目已见文档（跨所有轮次）
            seen_result = await db.execute(
                select(Document.source, Document.external_id)
                .join(RoundDocument, RoundDocument.document_id == Document.id)
                .join(SearchRound, SearchRound.id == RoundDocument.round_id)
                .where(SearchRound.project_id == job.project_id)
            )
            seen_keys = {(row[0], str(row[1])) for row in seen_result.all()}

            # 排除已在监控结果中出现的文档
            prev_results = await db.execute(
                select(MonitorResult).where(MonitorResult.job_id == job_id)
            )
            for prev in prev_results.scalars().all():
                if prev.docs:
                    for entry in prev.docs:
                        seen_keys.add((entry.get("source", ""), str(entry.get("external_id", ""))))

            new_docs = [
                d for d in all_docs
                if (d.get("source", ""), str(d.get("external_id", ""))) not in seen_keys
            ]

            # 5. 相关度打分，过滤高相关文档
            scored = []
            for doc in new_docs:
                score = keyword_score(doc, query_plan.expanded_terms, excluded_kw or None)
                if score >= 0.3:  # 低门槛，宁多勿少，监控阶段用户自己筛选
                    scored.append((score, doc))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_docs = [doc for _, doc in scored[:20]]  # 最多20篇

            if not top_docs:
                await _update_job_timestamps(job_id, now, db)
                return {"status": "ok", "new_docs": 0, "total_candidates": total}

            # 6. 保存新文档到 documents 表（复用 progressive_search 的保存逻辑）
            # 监控结果不创建 round_document，直接保存 Document
            saved_doc_ids = []
            for raw_doc in top_docs:
                r2 = await db.execute(
                    select(Document).where(
                        Document.source == raw_doc.get("source"),
                        Document.external_id == str(raw_doc.get("external_id", "")),
                    )
                )
                doc_obj = r2.scalar_one_or_none()
                if not doc_obj:
                    from dateutil import parser as dateparser
                    pub_date = None
                    raw_date = raw_doc.get("publication_date")
                    if raw_date:
                        try:
                            pub_date = dateparser.parse(str(raw_date)).date()
                        except Exception:
                            pass
                    doc_obj = Document(
                        source=raw_doc.get("source", "unknown"),
                        external_id=str(raw_doc.get("external_id", "")),
                        doc_type=raw_doc.get("doc_type", "paper"),
                        title=raw_doc.get("title", ""),
                        authors=raw_doc.get("authors"),
                        abstract=raw_doc.get("abstract"),
                        publication_date=pub_date,
                        url=raw_doc.get("url"),
                        doi=raw_doc.get("doi"),
                        journal=raw_doc.get("journal"),
                        citation_count=raw_doc.get("citation_count", 0),
                        pdf_url=raw_doc.get("pdf_url"),
                    )
                    db.add(doc_obj)
                    await db.flush()
                saved_doc_ids.append({
                    "document_id": str(doc_obj.id),
                    "source": raw_doc.get("source"),
                    "external_id": str(raw_doc.get("external_id", "")),
                    "title": raw_doc.get("title", ""),
                })

            # 7. 写入 monitor_results
            result_entry = MonitorResult(
                job_id=job_id,
                run_at=now,
                new_docs_found=len(top_docs),
                docs=saved_doc_ids,
                notified=False,
            )
            db.add(result_entry)

            # 8. 更新监控任务时间戳
            await _update_job_timestamps(job_id, now, db)
            await db.commit()

            # 9. 异步生成摘要（fire-and-forget，不阻塞监控任务）
            from app.workers.search_tasks import generate_summary_for_doc
            for entry in saved_doc_ids:
                generate_summary_for_doc.delay(
                    round_id_str=str(job_id),  # 用 job_id 作伪 round_id（摘要任务只用于查文档）
                    source=entry["source"],
                    external_id=entry["external_id"],
                    project_description=project.description,
                )

            logger.info("[Monitor] job=%s 完成：发现 %d 篇新文档（总候选 %d）", job_id_str, len(top_docs), total)
            return {"status": "ok", "new_docs": len(top_docs), "total_candidates": total}

    finally:
        await engine.dispose()


async def _update_job_timestamps(job_id: uuid.UUID, now: datetime, db):
    from sqlalchemy import update
    from app.models.monitor_job import MonitorJob

    next_run = now + timedelta(days=1)
    await db.execute(
        update(MonitorJob).where(MonitorJob.id == job_id).values(
            last_run_at=now,
            next_run_at=next_run,
        )
    )
