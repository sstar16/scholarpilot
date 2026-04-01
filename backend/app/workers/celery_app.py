from celery import Celery
from app.config import settings

app = Celery(
    "urip",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.search_tasks",
        "app.workers.monitor_tasks",
        "app.workers.embedding_tasks",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.search_tasks.*": {"queue": "default"},
        "app.workers.monitor_tasks.*": {"queue": "default"},
        "app.workers.fulltext_tasks.*": {"queue": "fulltext"},
        "app.workers.embedding_tasks.*": {"queue": "default"},
    },
    beat_schedule={
        "daily-monitor": {
            "task": "app.workers.monitor_tasks.run_daily_monitors",
            "schedule": 60 * 60 * 24,  # 每24小时（celery-beat 会在 UTC 06:00 触发）
        },
    },
)
