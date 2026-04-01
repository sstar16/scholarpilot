import logging
from celery import Celery
from celery.signals import worker_process_init
from app.config import settings

logger = logging.getLogger(__name__)

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


@worker_process_init.connect
def init_harness_in_worker(**kwargs):
    """
    Initialize Harness Engineering components in each Celery worker process.
    FastAPI lifespan only runs in the backend process — workers are separate.
    """
    try:
        from app.harness.tool_registry import init_tool_registry
        from app.harness.hook_engine import HookEngine
        from app.harness.hooks.logging_hook import register_logging_hooks
        from app.harness.hooks.metrics_hook import register_metrics_hooks
        from app.harness.skill_registry import SkillRegistry
        from app.harness.skills import deep_dive, trend_spotter, gap_finder

        registry = init_tool_registry()
        hook_engine = HookEngine.get_instance()
        register_logging_hooks(hook_engine)
        register_metrics_hooks(hook_engine)

        skill_registry = SkillRegistry.get_instance()
        skill_registry.register(deep_dive.DEFINITION, deep_dive.execute)
        skill_registry.register(trend_spotter.DEFINITION, trend_spotter.execute)
        skill_registry.register(gap_finder.DEFINITION, gap_finder.execute)

        logger.info(
            "[Harness/Worker] Initialized: %d tools, %d hooks, %d skills",
            registry.enabled_count, hook_engine.handler_count, skill_registry.skill_count,
        )
    except Exception as e:
        logger.warning("[Harness/Worker] Init failed (non-fatal): %s", e)
