"""
Workbench hook — subscribes to workbench hook points and republishes
them as SSE events on the session channel (sse:session:{session_id}).

Powers the Claude.ai-style AI workbench UI: streaming tokens, tool calls,
and live token/cost counter.

Session-scoped: every event must have session_id in the hook context.
Events without session_id are dropped silently (no-op).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.harness.hook_engine import HookEngine, HookPoint
from app.services.event_bus import EventBus

logger = logging.getLogger(__name__)


async def _on_llm_call_start(ctx: Dict[str, Any]) -> Dict[str, Any]:
    session_id = ctx.get("session_id")
    if not session_id:
        return ctx
    try:
        await EventBus.publish_session(session_id, "llm_call_start", {
            "call_id": ctx.get("call_id"),
            "provider": ctx.get("provider"),
            "model": ctx.get("model"),
            "prompt_preview": ctx.get("prompt_preview"),
            "agent_name": ctx.get("agent_name"),
        })
    except Exception as e:
        logger.debug("[Workbench] llm_call_start publish failed: %s", e)
    return ctx


async def _on_llm_call_end(ctx: Dict[str, Any]) -> Dict[str, Any]:
    session_id = ctx.get("session_id")
    if not session_id:
        return ctx
    try:
        usage = ctx.get("usage") or {}
        # Emit two events: full llm_call_end (per-call detail) and llm_usage_delta (for counter)
        await EventBus.publish_session(session_id, "llm_call_end", {
            "call_id": ctx.get("call_id"),
            "provider": ctx.get("provider"),
            "model": ctx.get("model"),
            "usage": usage,
            "cost_usd": ctx.get("cost_usd", 0.0),
            "latency_ms": ctx.get("latency_ms", 0),
            "finish_reason": ctx.get("finish_reason"),
            "text_preview": ctx.get("text_preview"),
            "agent_name": ctx.get("agent_name"),
            "status": ctx.get("status", "ok"),
        })
        await EventBus.publish_session(session_id, "llm_usage_delta", {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cost_usd": ctx.get("cost_usd", 0.0),
            "model": ctx.get("model"),
        })
    except Exception as e:
        logger.debug("[Workbench] llm_call_end publish failed: %s", e)
    return ctx


async def _on_tool_call_start(ctx: Dict[str, Any]) -> Dict[str, Any]:
    session_id = ctx.get("session_id")
    if not session_id:
        return ctx
    try:
        await EventBus.publish_session(session_id, "tool_call_start", {
            "call_id": ctx.get("call_id"),
            "tool_name": ctx.get("tool_name"),
            "args": ctx.get("args"),
            "agent_name": ctx.get("agent_name"),
        })
    except Exception as e:
        logger.debug("[Workbench] tool_call_start publish failed: %s", e)
    return ctx


async def _on_tool_call_end(ctx: Dict[str, Any]) -> Dict[str, Any]:
    session_id = ctx.get("session_id")
    if not session_id:
        return ctx
    try:
        await EventBus.publish_session(session_id, "tool_call_end", {
            "call_id": ctx.get("call_id"),
            "tool_name": ctx.get("tool_name"),
            "args": ctx.get("args"),
            "result_preview": _preview(ctx.get("result"), 400),
            "duration_ms": ctx.get("duration_ms", 0),
            "status": ctx.get("status", "ok"),
            "error": ctx.get("error"),
            "agent_name": ctx.get("agent_name"),
        })
    except Exception as e:
        logger.debug("[Workbench] tool_call_end publish failed: %s", e)
    return ctx


async def _on_agent_phase_change(ctx: Dict[str, Any]) -> Dict[str, Any]:
    session_id = ctx.get("session_id")
    if not session_id:
        return ctx
    try:
        await EventBus.publish_session(session_id, "agent_phase", {
            "agent_name": ctx.get("agent_name"),
            "from_phase": ctx.get("from_phase"),
            "to_phase": ctx.get("to_phase"),
            "description": ctx.get("description", ""),
        })
    except Exception as e:
        logger.debug("[Workbench] agent_phase publish failed: %s", e)
    return ctx


async def _on_agent_message_delta(ctx: Dict[str, Any]) -> Dict[str, Any]:
    session_id = ctx.get("session_id")
    if not session_id:
        return ctx
    try:
        await EventBus.publish_session(session_id, "agent_message_delta", {
            "message_id": ctx.get("message_id"),
            "agent_name": ctx.get("agent_name"),
            "delta": ctx.get("delta", ""),
            "done": ctx.get("done", False),
        })
    except Exception as e:
        logger.debug("[Workbench] agent_message_delta publish failed: %s", e)
    return ctx


def _preview(value: Any, max_len: int = 400) -> Any:
    """Best-effort serialization preview for tool results."""
    if value is None:
        return None
    try:
        import json as _json
        s = _json.dumps(value, ensure_ascii=False, default=str)
        return s[:max_len] + ("…" if len(s) > max_len else "")
    except Exception:
        s = str(value)
        return s[:max_len] + ("…" if len(s) > max_len else "")


def register_workbench_hooks(engine: HookEngine) -> None:
    """Register all workbench → SSE forwarding handlers."""
    engine.register(HookPoint.LLM_CALL_START, _on_llm_call_start, name="workbench.llm_start", priority=50)
    engine.register(HookPoint.LLM_CALL_END, _on_llm_call_end, name="workbench.llm_end", priority=50)
    engine.register(HookPoint.TOOL_CALL_START, _on_tool_call_start, name="workbench.tool_start", priority=50)
    engine.register(HookPoint.TOOL_CALL_END, _on_tool_call_end, name="workbench.tool_end", priority=50)
    engine.register(HookPoint.AGENT_PHASE_CHANGE, _on_agent_phase_change, name="workbench.phase", priority=50)
    engine.register(HookPoint.AGENT_MESSAGE_DELTA, _on_agent_message_delta, name="workbench.message_delta", priority=50)
    logger.info("[Workbench] registered 6 SSE-forwarding hook handlers")
