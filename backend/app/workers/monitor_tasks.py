"""
Celery 定时任务：每日监控
"""
from app.workers.celery_app import app as celery_app


@celery_app.task(name="app.workers.monitor_tasks.run_daily_monitors")
def run_daily_monitors():
    """触发所有活跃的每日监控任务"""
    import asyncio

    async def _run():
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy import select
        from app.config import settings
        from app.models.monitor_job import MonitorJob

        engine = create_async_engine(settings.database_url, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            result = await db.execute(
                select(MonitorJob).where(MonitorJob.is_active == True, MonitorJob.schedule == "daily")
            )
            jobs = result.scalars().all()
            job_ids = [str(j.id) for j in jobs]

        await engine.dispose()
        return job_ids

    loop = asyncio.new_event_loop()
    job_ids = loop.run_until_complete(_run())
    loop.close()

    for job_id in job_ids:
        run_single_monitor.delay(job_id)

    return {"triggered": len(job_ids)}


@celery_app.task(name="app.workers.monitor_tasks.run_single_monitor", bind=True, max_retries=1)
def run_single_monitor(self, job_id: str):
    """执行单个监控任务（Phase 1 骨架，Phase 2 完整实现）"""
    # Phase 1: 占位实现，Phase 2 补充完整抓取 + 去重 + 摘要 + 通知逻辑
    print(f"[Monitor] 执行监控任务: {job_id}")
    return {"job_id": job_id, "status": "skipped_phase1"}
