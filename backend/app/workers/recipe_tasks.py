"""Project recipe regeneration as a fire-and-forget Celery task.

Triggered from the classification endpoint after every bucket update. Cheap
(< 100ms typical), but going async keeps the API response fast.

Debouncing: Redis SET NX EX 60 — when a user batch-classifies a stack of
documents, we don't need 10 regen runs in a row. The first task acquires the
lock, subsequent ones (within 60s) become no-ops. Lock is intentionally not
released on success: the TTL is the dedup window. On Redis outage we fall
back to "always run", which is correct (last-write-wins persists the same
result anyway).
"""
import logging
import uuid

from app.workers.celery_app import app as celery_app
from app.workers.search_tasks import _run_async

logger = logging.getLogger(__name__)


_DEDUP_TTL_SECONDS = 60


def _try_acquire_dedup_lock(project_id_str: str) -> bool:
    """Returns True if this caller acquired the regen window for the project.
    On any Redis error we return True (i.e. let the task run) — safer to
    duplicate work than to silently swallow a real classification update."""
    try:
        import redis as _redis
        from app.config import settings
        client = _redis.Redis.from_url(settings.redis_url)
        # SET key value NX EX ttl  → returns None if key exists
        acquired = client.set(
            f"recipe_regen:{project_id_str}",
            "1", nx=True, ex=_DEDUP_TTL_SECONDS,
        )
        return bool(acquired)
    except Exception as e:
        logger.warning(
            "[recipe] dedup lock unavailable, running anyway: %s", e,
        )
        return True


@celery_app.task(
    name="app.workers.recipe_tasks.regenerate_project_recipe_task",
    bind=True,
    max_retries=1,
    ignore_result=True,
)
def regenerate_project_recipe_task(self, project_id_str: str, user_id_str: str):
    """Compute + persist auto_recipe_md for the given project. Idempotent
    on success; first-wins debouncing dedups bursts within 60s."""
    if not _try_acquire_dedup_lock(project_id_str):
        logger.info(
            "[recipe] dedup skip project=%s (within %ds window)",
            project_id_str[:8], _DEDUP_TTL_SECONDS,
        )
        return {"status": "deduped"}
    try:
        return _run_async(_run(project_id_str, user_id_str))
    except Exception as e:
        logger.error(
            "[recipe] regenerate failed project=%s user=%s: %s",
            project_id_str[:8], user_id_str[:8], e,
        )
        return {"status": "failed", "error": str(e)}


async def _run(project_id_str: str, user_id_str: str):
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )

    from app.config import settings
    from app.services.project_recipe import regenerate_project_recipe

    engine = create_async_engine(settings.database_url, echo=False)
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    try:
        async with sessionmaker() as db:
            await regenerate_project_recipe(
                project_id=uuid.UUID(project_id_str),
                user_id=uuid.UUID(user_id_str),
                db=db,
            )
        return {"status": "ok"}
    finally:
        await engine.dispose()
