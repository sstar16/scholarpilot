"""
Celery 任务：生成并更新用户画像的向量 embedding
在每次反馈提交后异步触发，用 SentenceTransformer(all-MiniLM-L6-v2) 计算
正向/负向文档的均值向量，存入 UserProfile.positive_embedding / negative_embedding

HF_ENDPOINT=https://hf-mirror.com 可通过环境变量指定镜像站（已在 docker-compose 中配置）
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


@celery_app.task(name="app.workers.embedding_tasks.update_profile_embedding", bind=True, max_retries=1)
def update_profile_embedding(self, user_id: str, project_id: str):
    """更新用户画像的正向/负向 embedding 向量（feedback 后异步触发）"""
    try:
        return _run_async(_update_embedding_async(user_id, project_id))
    except Exception as e:
        logger.error("[embedding_tasks] 更新失败 project=%s: %s", project_id, e)
        return {"status": "failed", "error": str(e)}


async def _update_embedding_async(user_id_str: str, project_id_str: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    import numpy as np

    from app.config import settings
    from app.models.user_profile import UserProfile
    from app.models.document import Document
    from app.models.feedback import Feedback
    from app.models.search_round import SearchRound
    from app.services.profile_service import get_or_create_profile

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.error("[embedding_tasks] sentence-transformers 未安装，跳过")
        return {"status": "skipped", "reason": "sentence-transformers not installed"}

    project_id = uuid.UUID(project_id_str)
    user_id = uuid.UUID(user_id_str)

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            # 查询正向反馈文档（relevance >= 1）
            pos_result = await db.execute(
                select(Document.title, Document.abstract)
                .join(Feedback, Feedback.document_id == Document.id)
                .join(SearchRound, SearchRound.id == Feedback.round_id)
                .where(
                    SearchRound.project_id == project_id,
                    Feedback.user_id == user_id,
                    Feedback.relevance >= 1,
                )
            )
            pos_rows = pos_result.all()

            # 查询负向反馈文档（relevance == -1）
            neg_result = await db.execute(
                select(Document.title, Document.abstract)
                .join(Feedback, Feedback.document_id == Document.id)
                .join(SearchRound, SearchRound.id == Feedback.round_id)
                .where(
                    SearchRound.project_id == project_id,
                    Feedback.user_id == user_id,
                    Feedback.relevance == -1,
                )
            )
            neg_rows = neg_result.all()

            if not pos_rows and not neg_rows:
                logger.info("[embedding_tasks] project=%s 无反馈文档，跳过", project_id_str)
                return {"status": "skipped", "reason": "no feedback docs"}

            # 加载模型（首次约 2s；之后从缓存读取）
            logger.info("[embedding_tasks] 加载 SentenceTransformer 模型...")
            model = SentenceTransformer("all-MiniLM-L6-v2")

            pos_emb = None
            neg_emb = None

            if pos_rows:
                pos_texts = [f"{r[0] or ''} {r[1] or ''}".strip() for r in pos_rows]
                pos_vecs = model.encode(pos_texts, show_progress_bar=False)
                pos_emb = np.mean(pos_vecs, axis=0).tolist()

            if neg_rows:
                neg_texts = [f"{r[0] or ''} {r[1] or ''}".strip() for r in neg_rows]
                neg_vecs = model.encode(neg_texts, show_progress_bar=False)
                neg_emb = np.mean(neg_vecs, axis=0).tolist()

            # 保存到 UserProfile
            profile = await get_or_create_profile(user_id, project_id, db)
            if pos_emb is not None:
                profile.positive_embedding = pos_emb
            if neg_emb is not None:
                profile.negative_embedding = neg_emb
            await db.commit()

            logger.info(
                "[embedding_tasks] 更新完成 project=%s pos=%d docs neg=%d docs",
                project_id_str, len(pos_rows), len(neg_rows),
            )
            return {"status": "ok", "pos_count": len(pos_rows), "neg_count": len(neg_rows)}
    finally:
        await engine.dispose()
