"""
Structured logging hook — emits JSON log lines at each hook point.
Replaces scattered logger.info() calls with a unified, machine-parseable format.
"""
import json
import logging
from typing import Any, Dict

from app.harness.hook_engine import HookEngine, HookPoint

logger = logging.getLogger("harness.hooks.logging")


async def _log_hook(context: Dict[str, Any]) -> Dict[str, Any]:
    """Generic structured log emitter."""
    hook_point = context.get("_hook_point", "unknown")
    # Build a loggable subset (exclude large data like full doc lists)
    log_data = {
        k: v for k, v in context.items()
        if not k.startswith("_") and not isinstance(v, (list, bytes))
    }
    # Include list lengths instead of full lists
    for k, v in context.items():
        if isinstance(v, list):
            log_data[f"{k}_count"] = len(v)

    logger.info("[%s] %s", hook_point, json.dumps(log_data, default=str, ensure_ascii=False))

    # Write to DevTools PG buffer
    try:
        from app.services.devtools.log_writer import log_buffer
        # Ensure round_id/project_id are strings or None (not UUID objects)
        rid = context.get("round_id")
        pid = context.get("project_id")
        log_buffer.add({
            "level": "INFO",
            "source": "hook",
            "category": hook_point,
            "message": f"[{hook_point}]",
            "context": log_data,
            "round_id": str(rid) if rid else None,
            "project_id": str(pid) if pid else None,
        })
    except Exception as e:
        import traceback
        logger.warning("DevTools hook log failed: %s\n%s", e, traceback.format_exc())

    return context


def register_logging_hooks(engine: HookEngine) -> None:
    """Register the logging hook at all hook points (low priority = fires first)."""
    for point in HookPoint:
        async def handler(ctx, pt=point):
            ctx["_hook_point"] = pt.value
            return await _log_hook(ctx)

        engine.register(point, handler, name=f"logging_{point.value}", priority=10)
