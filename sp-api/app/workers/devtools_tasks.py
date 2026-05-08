"""DevTools tasks — sp-api 版。

仅保留 cleanup_old_devlogs（清 7 天前的 dev_logs 行）。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models.dev_log import DevLog
from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)


def _sync_engine():
    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    return create_engine(sync_url, echo=False, pool_size=2, max_overflow=3)


@celery_app.task(name="app.workers.devtools_tasks.cleanup_old_devlogs")
def cleanup_old_devlogs() -> dict:
    """删 7 天前的 dev_logs。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    engine = _sync_engine()
    try:
        with Session(engine) as session:
            r = session.execute(delete(DevLog).where(DevLog.created_at < cutoff))
            session.commit()
            return {"deleted": r.rowcount}
    finally:
        engine.dispose()
