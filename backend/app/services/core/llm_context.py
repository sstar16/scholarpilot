"""
Context propagation for LLM observability hooks.

Callers set session_id / round_id / agent_name / call parent context via
`set_llm_context(...)` before calling `generate_full()` or `generate_stream()`.
The LLMProviderManager reads this to populate LLM_CALL_START/END hook events.

Use a context manager for clean scoping:

    async with llm_context(session_id="abc", agent_name="IntentAgent"):
        result = await manager.generate_full(prompt)
"""
from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMContext:
    session_id: Optional[str] = None
    round_id: Optional[str] = None
    agent_name: str = "unknown"
    parent_call_id: Optional[str] = None


_llm_context: contextvars.ContextVar[Optional[LLMContext]] = contextvars.ContextVar(
    "llm_context", default=None
)


def get_llm_context() -> LLMContext:
    ctx = _llm_context.get()
    if ctx is None:
        return LLMContext()
    return ctx


def set_llm_context(ctx: LLMContext) -> contextvars.Token:
    return _llm_context.set(ctx)


def reset_llm_context(token: contextvars.Token) -> None:
    _llm_context.reset(token)


@contextlib.contextmanager
def llm_context(
    *,
    session_id: Optional[str] = None,
    round_id: Optional[str] = None,
    agent_name: str = "unknown",
):
    """Sync context manager for setting LLM context. Use via `with`."""
    current = get_llm_context()
    new = LLMContext(
        session_id=session_id or current.session_id,
        round_id=round_id or current.round_id,
        agent_name=agent_name,
    )
    token = set_llm_context(new)
    try:
        yield new
    finally:
        reset_llm_context(token)


@contextlib.asynccontextmanager
async def async_llm_context(
    *,
    session_id: Optional[str] = None,
    round_id: Optional[str] = None,
    agent_name: str = "unknown",
):
    """Async context manager variant."""
    current = get_llm_context()
    new = LLMContext(
        session_id=session_id or current.session_id,
        round_id=round_id or current.round_id,
        agent_name=agent_name,
    )
    token = set_llm_context(new)
    try:
        yield new
    finally:
        reset_llm_context(token)


async def emit_phase(phase: str, description: str = "") -> None:
    """
    Fire AGENT_PHASE_CHANGE hook for the current llm_context.
    No-op if no session_id in context. Best-effort (never raises).
    """
    try:
        from app.harness.hook_engine import HookEngine, HookPoint
    except Exception:
        return
    ctx = get_llm_context()
    if not ctx.session_id:
        return
    try:
        await HookEngine.get_instance().fire(HookPoint.AGENT_PHASE_CHANGE, {
            "agent_name": ctx.agent_name,
            "session_id": ctx.session_id,
            "round_id": ctx.round_id,
            "to_phase": phase,
            "description": description,
        })
    except Exception:
        pass


async def emit_tool_call(
    tool_name: str,
    args: Optional[dict] = None,
    result: Any = None,
    duration_ms: int = 0,
    status: str = "ok",
    error: Optional[str] = None,
) -> None:
    """
    Fire TOOL_CALL_END hook for the current llm_context.
    Convenience for the common case: tool invoked + completed in one shot.
    For long-running tools, fire TOOL_CALL_START first via HookEngine directly.
    """
    try:
        from app.harness.hook_engine import HookEngine, HookPoint
    except Exception:
        return
    ctx = get_llm_context()
    if not ctx.session_id:
        return
    import uuid as _uuid
    call_id = _uuid.uuid4().hex[:12]
    try:
        await HookEngine.get_instance().fire(HookPoint.TOOL_CALL_END, {
            "call_id": call_id,
            "tool_name": tool_name,
            "args": args or {},
            "result": result,
            "duration_ms": duration_ms,
            "status": status,
            "error": error,
            "agent_name": ctx.agent_name,
            "session_id": ctx.session_id,
            "round_id": ctx.round_id,
        })
    except Exception:
        pass
