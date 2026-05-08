"""每日清理过期的 round cache（用户客户端已经有本地副本，云端只是 7 天 TTL 缓存）。"""
import asyncio
import logging
from datetime import datetime, timezone

from celery import current_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@current_app.task(name="app.workers.cleanup_tasks.cleanup_expired_round_cache")
def cleanup_expired_round_cache() -> dict:
    return _run_async(_cleanup_async())


async def _cleanup_async(db=None) -> dict:
    """删 expires_at < NOW() 的 search_rounds（CASCADE 带走 round_documents）。

    `db` 可注入：测试用 conftest 的 `db` fixture（确保跑在 test DB 上）；
    生产 worker 不传 → 内部创建独立 engine + 用 settings.database_url。
    """
    from sqlalchemy import delete, select
    from app.models.search_round import SearchRound

    if db is not None:
        return await _do_cleanup(db)

    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )
    from app.config import settings

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as own_db:
            return await _do_cleanup(own_db)
    finally:
        await engine.dispose()


async def _do_cleanup(db) -> dict:
    from sqlalchemy import delete, select
    from app.models.search_round import SearchRound

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SearchRound.id).where(SearchRound.expires_at < now)
    )
    expired_ids = [row[0] for row in result.all()]
    if not expired_ids:
        logger.info("[cleanup_expired_round_cache] no expired rounds")
        return {"deleted": 0}

    # 删 round —— round_documents 由 ON DELETE CASCADE 带走
    # documents（全局表）不动 — 可能被其它 round 引用
    await db.execute(
        delete(SearchRound).where(SearchRound.id.in_(expired_ids))
    )
    await db.commit()
    logger.info(
        "[cleanup_expired_round_cache] deleted %d expired rounds: %s",
        len(expired_ids), expired_ids[:5],
    )
    return {"deleted": len(expired_ids)}
