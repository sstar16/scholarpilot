import logging
from celery import Celery
from celery.schedules import crontab
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
        "app.workers.devtools_tasks",
        "app.workers.fulltext_tasks",
        "app.workers.graph_tasks",
        "app.workers.literature_tasks",
        "app.workers.import_tasks",
        "app.workers.cleanup_tasks",
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
        "app.workers.graph_tasks.*": {"queue": "default"},
        "app.workers.literature_tasks.*": {"queue": "default"},
        "app.workers.import_tasks.*": {"queue": "default"},
        "app.workers.cleanup_tasks.*": {"queue": "default"},
    },
    beat_schedule={
        "daily-monitor": {
            "task": "app.workers.monitor_tasks.run_daily_monitors",
            "schedule": 60 * 60 * 24,  # 每24小时（celery-beat 会在 UTC 06:00 触发）
        },
        "cleanup-devlogs": {
            "task": "app.workers.devtools_tasks.cleanup_old_devlogs",
            "schedule": 60 * 60 * 24,  # 每日清理 7 天前的日志
        },
        "cleanup-import-tmp": {
            "task": "app.workers.import_tasks.cleanup_import_tmp_files",
            "schedule": crontab(hour=3, minute=0),  # 每日 03:00 清理失败/取消 job 临时文件
        },
        # M3 P0 follow-up F1：自动 cleanup 暂时禁用 — web 用户没客户端副本时云端是唯一来源，
        # 自动删 7d 前的 round 会让历史丢失。改为 DevTools 手动触发（POST /api/devtools/cleanup-rounds/run）
        # 或后续等 client 用户占多数后重新启用。
        # "cleanup-expired-rounds": {
        #     "task": "app.workers.cleanup_tasks.cleanup_expired_round_cache",
        #     "schedule": crontab(hour=3, minute=30),
        # },
    },
)


from celery.signals import task_prerun, task_postrun, task_failure
from collections import OrderedDict
import time as _time


class _BoundedTaskTimes(OrderedDict):
    """Bounded dict for task start times — evicts oldest beyond 500 entries."""
    _MAXSIZE = 500
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self._MAXSIZE:
            self.popitem(last=False)


_task_start_times = _BoundedTaskTimes()


@task_prerun.connect
def devtools_task_prerun(sender=None, task_id=None, task=None, **kwargs):
    _task_start_times[task_id] = _time.time()


@task_postrun.connect
def devtools_task_postrun(sender=None, task_id=None, task=None, retval=None, state=None, **kwargs):
    start = _task_start_times.pop(task_id, None)
    duration_ms = int((_time.time() - start) * 1000) if start else None
    try:
        from app.services.devtools.log_writer import log_buffer
        log_buffer.add({
            "level": "INFO",
            "source": "celery",
            "category": task.name if task else "unknown",
            "message": f"Task {task.name} completed ({state}, {duration_ms}ms)",
            "duration_ms": duration_ms,
        })
        log_buffer.sync_flush()
    except Exception:
        pass


@task_failure.connect
def devtools_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    start = _task_start_times.pop(task_id, None)
    duration_ms = int((_time.time() - start) * 1000) if start else None
    try:
        from app.services.devtools.log_writer import log_buffer
        log_buffer.add({
            "level": "ERROR",
            "source": "celery",
            "category": sender.name if sender else "unknown",
            "message": f"Task {sender.name if sender else 'unknown'} FAILED: {exception}",
            "duration_ms": duration_ms,
            "error_trace": str(traceback) if traceback else None,
        })
        log_buffer.sync_flush()
    except Exception:
        pass


@worker_process_init.connect
def init_harness_in_worker(**kwargs):
    """
    Initialize Harness Engineering components in each Celery worker process.
    FastAPI lifespan only runs in the backend process — workers are separate.
    统一走 bootstrap.setup_harness() 确保与 backend 完全一致（8 skills + 业务 hooks）。
    """
    try:
        from app.harness.bootstrap import setup_harness
        counts = setup_harness()
        logger.info(
            "[Harness/Worker] Initialized: %d tools, %d hooks, %d skills",
            counts["tools"], counts["hooks"], counts["skills"],
        )
    except Exception as e:
        logger.warning("[Harness/Worker] Init failed (non-fatal): %s", e)
