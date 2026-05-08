"""
DevTools cleanup task — deletes dev_logs older than 7 days.
"""
import logging
from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.devtools_tasks.cleanup_old_devlogs")
def cleanup_old_devlogs():
    """Delete dev_logs older than 7 days."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.config import settings

    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url, echo=False)
    try:
        with Session(engine) as session:
            result = session.execute(
                text("DELETE FROM dev_logs WHERE created_at < now() - interval '7 days'")
            )
            session.commit()
            deleted = result.rowcount
            logger.info("[DevTools] Cleaned up %d old log entries", deleted)
    finally:
        engine.dispose()
