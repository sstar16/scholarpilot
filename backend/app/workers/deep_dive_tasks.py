"""
Celery 任务：Deep Dive 深度文献分析
用户触发，异步执行 PDF 下载 + 全文分析。
"""
import asyncio
import logging
import uuid

from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.workers.deep_dive_tasks.execute_deep_dive", bind=True, max_retries=1)
def execute_deep_dive(self, document_id: str, project_id: str):
    """Deep Dive 任务：下载 PDF + 提取文本 + LLM 深度分析"""
    return _run_async(_execute_deep_dive_async(document_id, project_id))


async def _execute_deep_dive_async(document_id_str: str, project_id_str: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.project import Project
    from app.models.user_profile import UserProfile

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    doc_id = uuid.UUID(document_id_str)
    project_id = uuid.UUID(project_id_str)

    async with session_factory() as db:
        try:
            # 获取文档和项目
            doc_result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = doc_result.scalar_one_or_none()
            if not doc:
                return {"error": "Document not found"}

            proj_result = await db.execute(select(Project).where(Project.id == project_id))
            project = proj_result.scalar_one_or_none()
            if not project:
                return {"error": "Project not found"}

            # 加载 LLM
            from app.services.core.llm_config_store import get_llm_manager
            llm_manager = await get_llm_manager()

            # 加载用户记忆
            user_memory = ""
            profile_result = await db.execute(
                select(UserProfile).where(
                    UserProfile.project_id == project_id,
                )
            )
            profile = profile_result.scalar_one_or_none()
            if profile and profile.memory_text:
                user_memory = profile.memory_text

            # 执行深度分析
            from app.harness.deep_dive_agent import DeepDiveAgent
            agent = DeepDiveAgent(
                llm_manager=llm_manager,
                pdf_storage_path=settings.pdf_storage_path,
            )

            doc_dict = {
                "title": doc.title,
                "authors": doc.authors,
                "abstract": doc.abstract,
                "source": doc.source,
                "publication_date": str(doc.publication_date) if doc.publication_date else None,
                "doi": doc.doi,
                "pdf_url": doc.pdf_url,
                "fulltext_text": doc.fulltext_text,
                "ai_summary": doc.ai_summary,
            }

            result = await agent.analyze(
                doc=doc_dict,
                project_description=project.description,
                user_memory=user_memory,
                project_id=str(project_id),
            )

            if not result:
                return {"document_id": document_id_str, "status": "failed", "error": "Analysis returned no result"}

            # 更新文档
            if result.get("updated_one_liner"):
                doc.one_line_summary = result["updated_one_liner"]
            if result.get("content_source") in ("pdf_fulltext", "cached_fulltext"):
                doc.fulltext_status = "available"
            await db.commit()

            # 缓存到 Redis（1h TTL）
            try:
                import json
                import redis.asyncio as aioredis
                r = aioredis.from_url(settings.redis_url)
                await r.set(
                    f"deep_dive:{document_id_str}",
                    json.dumps(result, ensure_ascii=False),
                    ex=3600,
                )
                await r.close()
            except Exception as e:
                logger.warning("[DeepDive] Redis 缓存失败: %s", e)

            # SSE 通知
            try:
                from app.services.event_bus import EventBus
                # 找到该文档所在的最新 round_id 来发 SSE
                from app.models.round_document import RoundDocument
                rd_q = await db.execute(
                    select(RoundDocument.round_id).where(
                        RoundDocument.document_id == doc_id
                    ).order_by(RoundDocument.round_id.desc()).limit(1)
                )
                rd_row = rd_q.first()
                if rd_row:
                    EventBus.publish_sync(str(rd_row[0]), "deep_dive_complete", {
                        "document_id": document_id_str,
                        "content_source": result.get("content_source", "unknown"),
                    })
            except Exception:
                pass

            logger.info("[DeepDive] 完成: %s (%s)", doc.title[:50], result.get("content_source"))
            return {
                "document_id": document_id_str,
                "status": "completed",
                "content_source": result.get("content_source"),
                "analysis": result,
            }

        except Exception as e:
            logger.error("[DeepDive] 任务失败: %s", e, exc_info=True)
            return {"document_id": document_id_str, "status": "failed", "error": str(e)}
        finally:
            await engine.dispose()
