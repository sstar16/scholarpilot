"""
Metrics hook — records timing counters in Redis for observability.
Tracks: round execution time, per-source latency, LLM call count.
"""
import logging
import time
from typing import Any, Dict, Optional

from app.harness.hook_engine import HookEngine, HookPoint

logger = logging.getLogger("harness.hooks.metrics")

# In-memory metrics (lightweight, no Redis dependency required)
_metrics: Dict[str, Any] = {
    "rounds_started": 0,
    "rounds_completed": 0,
    "total_search_ms": 0,
    "feedbacks_received": 0,
    "source_stats": {},  # source_id -> {"invocations": N, "total_ms": N}
}


def get_metrics() -> Dict[str, Any]:
    """Return current metrics snapshot."""
    return dict(_metrics)


async def _on_round_start(context: Dict[str, Any]) -> Dict[str, Any]:
    _metrics["rounds_started"] += 1
    context["_round_start_time"] = time.time()
    return context


async def _on_post_search(context: Dict[str, Any]) -> Dict[str, Any]:
    source_stats = context.get("source_stats", {})
    for src_id, stats in source_stats.items():
        if src_id not in _metrics["source_stats"]:
            _metrics["source_stats"][src_id] = {"invocations": 0, "total_ms": 0, "total_docs": 0}
        _metrics["source_stats"][src_id]["invocations"] += 1
        _metrics["source_stats"][src_id]["total_ms"] += stats.get("execution_ms", 0)
        _metrics["source_stats"][src_id]["total_docs"] += stats.get("count", 0)
    return context


async def _on_round_complete(context: Dict[str, Any]) -> Dict[str, Any]:
    _metrics["rounds_completed"] += 1
    start = context.get("_round_start_time")
    if start:
        _metrics["total_search_ms"] += int((time.time() - start) * 1000)
    return context


async def _on_post_feedback(context: Dict[str, Any]) -> Dict[str, Any]:
    _metrics["feedbacks_received"] += 1
    return context


def register_metrics_hooks(engine: HookEngine) -> None:
    """Register metrics hooks at relevant lifecycle points."""
    engine.register(HookPoint.ROUND_START, _on_round_start, name="metrics_round_start", priority=20)
    engine.register(HookPoint.POST_SEARCH, _on_post_search, name="metrics_post_search", priority=20)
    engine.register(HookPoint.ROUND_COMPLETE, _on_round_complete, name="metrics_round_complete", priority=20)
    engine.register(HookPoint.POST_FEEDBACK, _on_post_feedback, name="metrics_post_feedback", priority=20)
