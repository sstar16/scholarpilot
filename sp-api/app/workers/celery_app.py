"""Celery app — sp-api 版（裁剪版 backend celery_app.py）。

vs backend/app/workers/celery_app.py 改动：
- include 仅 fulltext_tasks / import_tasks / devtools_tasks（删 search/monitor/graph/literature/recipe/cleanup）
- beat schedule 删 daily-monitor + cleanup-expired-rounds（sp-api 没 monitor/round 表）
- 保留 cleanup-devlogs + cleanup-import-tmp（清磁盘垃圾）
- 删 worker_process_init 里的 harness setup（sp-api 没有 harness/skills 系统）
"""
import logging
from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    task_prerun, task_postrun, task_failure,
)
from collections import OrderedDict
import time as _time

from app.config import settings

logger = logging.getLogger(__name__)

app = Celery(
    "sp-api",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.fulltext_tasks",
        "app.workers.import_tasks",
        "app.workers.devtools_tasks",
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
        "app.workers.fulltext_tasks.*": {"queue": "fulltext"},
        "app.workers.import_tasks.*": {"queue": "default"},
        "app.workers.devtools_tasks.*": {"queue": "default"},
    },
    beat_schedule={
        "cleanup-devlogs": {
            "task": "app.workers.devtools_tasks.cleanup_old_devlogs",
            "schedule": 60 * 60 * 24,  # 每日清理 7 天前的日志
        },
        "cleanup-import-tmp": {
            "task": "app.workers.import_tasks.cleanup_import_tmp_files",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)


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
