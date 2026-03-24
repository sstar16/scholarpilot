"""
Celery 任务：执行单轮渐进式检索
流程：检索 → 保存文档 → 生成 AI 摘要 → chord callback 更新状态
"""
import asyncio
import uuid
from celery import chord, group
from app.workers.celery_app import app as celery_app


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

            # 3. 构建查询计划
            query_plan = build_query(
                project_description=project.description,
                project_domain=project.domain,
                round_number=round_.round_number,
            )

            # 4. 执行并行检索
            selected_docs, total_candidates = await execute_search(query_plan)

            # 5. 保存文档到数据库
            await save_round_documents(round_id, selected_docs, db)

            # 6. 若无文档则直接进入等待反馈
            if not selected_docs:
                await mark_round_awaiting_feedback(round_id, db)
                return {"round_id": round_id_str, "selected": 0, "total": total_candidates}

            # 7. 标记为摘要生成中
            await mark_round_summarizing(round_id, total_candidates, len(selected_docs), db)

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
            import traceback
            print(f"[execute_round] 错误: {e}\n{traceback.format_exc()}")
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
        print(f"[generate_summary_for_doc] 失败 source={source} external_id={external_id}: {e}")
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

            # 使用 Ollama 或已配置的 LLM（此处用默认配置）
            llm_manager = LLMProviderManager(default_ollama_host=settings.ollama_host)
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

            print(f"[finalize_round] round={round_id_str} 摘要完成 {done_count}/{total_count}")

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
