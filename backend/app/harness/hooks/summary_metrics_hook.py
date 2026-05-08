"""
POST_SUMMARIZE hook — 摘要完成后更新 Redis 统计（B3）

触发时机：每篇文档 summary 任务成功写库后（search_tasks.generate_summary_for_doc）
动作：
  - INCR llm:summary_count:{round_id}
  - 记录 last_summary_at 时间戳
用途：DevTools 实时看到摘要 pipeline 的健康度；feedback 给用户"本轮已处理 N 篇"
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from app.harness.hook_engine import HookEngine, HookPoint

logger = logging.getLogger(__name__)


async def track_summary_metrics(ctx: Dict[str, Any]) -> Dict[str, Any]:
    round_id = ctx.get("round_id")
    if not round_id:
        return ctx

    try:
        import redis.asyncio as aioredis
        from app.config import settings
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            pipe = r.pipeline()
            pipe.incr(f"llm:summary_count:{round_id}")
            pipe.set(f"llm:last_summary_at:{round_id}", str(int(time.time())), ex=3600)
            await pipe.execute()
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug("[summary_metrics] redis write failed (benign): %s", e)

    return ctx


def register_summary_metrics_hook(engine: HookEngine) -> None:
    engine.register(
        HookPoint.POST_SUMMARIZE,
        track_summary_metrics,
        name="summary_metrics",
        priority=50,
    )
