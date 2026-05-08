"""
Hook Engine — lightweight lifecycle event system for pipeline extensibility.

Adapted from Claude Code's hook system (AsyncHookRegistry pattern).
Each HookPoint represents a natural boundary in the search pipeline.
Handlers are called in priority order; zero overhead when no handlers registered.
"""
import logging
import time
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Handler type: async function that takes context dict, returns (possibly modified) context dict
HookHandler = Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]


class HookPoint(str, Enum):
    """Lifecycle boundaries where hooks can fire.

    Pipeline-level (round/project/monitoring lifecycle)
    and workbench-level (tool/LLM/agent phase observability).

    ## Workbench hook context schemas (for the AI Workbench streaming UI)

    - TOOL_CALL_START: {
          tool_name: str, call_id: str, args: dict,
          agent_name: str, session_id: str, round_id: str | None
      }
    - TOOL_CALL_END: {
          tool_name: str, call_id: str, args: dict,
          result: Any, duration_ms: int, status: "ok"|"error",
          agent_name: str, session_id: str, round_id: str | None,
          error: str | None
      }
    - LLM_CALL_START: {
          call_id: str, provider: str, model: str,
          prompt_preview: str, agent_name: str, session_id: str,
          round_id: str | None
      }
    - LLM_CALL_END: {
          call_id: str, provider: str, model: str,
          usage: LLMUsage, cost_usd: float, latency_ms: int,
          finish_reason: str | None, text_preview: str,
          agent_name: str, session_id: str, round_id: str | None
      }
    - AGENT_PHASE_CHANGE: {
          agent_name: str, from_phase: str | None, to_phase: str,
          session_id: str, round_id: str | None, description: str
      }
    - AGENT_MESSAGE_DELTA: {
          agent_name: str, message_id: str, delta: str,
          done: bool, session_id: str, round_id: str | None,
          usage_delta: LLMUsage | None
      }
    """
    ROUND_START = "round_start"
    POST_SEARCH = "post_search"
    PRE_SCORING = "pre_scoring"
    POST_SCORING = "post_scoring"
    PRE_SUMMARIZE = "pre_summarize"
    POST_SUMMARIZE = "post_summarize"
    ROUND_COMPLETE = "round_complete"
    PRE_FEEDBACK = "pre_feedback"
    POST_FEEDBACK = "post_feedback"
    PROJECT_CREATE = "project_create"
    MONITOR_TRIGGER = "monitor_trigger"
    # Phase 3.0 — Conversation-driven hooks
    CONVERSATION_START = "conversation_start"
    INTENT_ANALYZED = "intent_analyzed"
    INTENT_CONFIRMED = "intent_confirmed"
    SEARCH_MODE_SELECTED = "search_mode_selected"
    INVESTIGATION_START = "investigation_start"
    INVESTIGATION_END = "investigation_end"
    MONITOR_PUSH_GENERATED = "monitor_push_generated"
    # Workbench hooks — fuel the Claude.ai-style streaming UI
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    LLM_CALL_START = "llm_call_start"
    LLM_CALL_END = "llm_call_end"
    AGENT_PHASE_CHANGE = "agent_phase_change"
    AGENT_MESSAGE_DELTA = "agent_message_delta"


class HookEngine:
    """
    Singleton hook engine. Handlers registered per HookPoint with priority.
    Lower priority number = fires first.
    """

    _instance: Optional["HookEngine"] = None

    def __init__(self):
        self._handlers: Dict[HookPoint, List[Tuple[int, str, HookHandler]]] = {}

    @classmethod
    def get_instance(cls) -> "HookEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        cls._instance = None

    def register(
        self,
        point: HookPoint,
        handler: HookHandler,
        name: str = "",
        priority: int = 100,
    ) -> None:
        """Register a handler for a hook point."""
        if point not in self._handlers:
            self._handlers[point] = []
        self._handlers[point].append((priority, name or handler.__name__, handler))
        self._handlers[point].sort(key=lambda x: x[0])
        logger.debug("[HookEngine] 注册 %s: %s (priority=%d)", point.value, name, priority)

    async def fire(self, point: HookPoint, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fire all handlers for a hook point in priority order.
        Returns the (possibly modified) context dict.
        Zero overhead if no handlers registered.
        """
        handlers = self._handlers.get(point)
        if not handlers:
            return context

        t0 = time.time()
        for priority, name, handler in handlers:
            try:
                context = await handler(context) or context
            except Exception as e:
                logger.warning(
                    "[HookEngine] %s handler '%s' failed: %s",
                    point.value, name, e,
                )
        elapsed_ms = int((time.time() - t0) * 1000)

        if elapsed_ms > 100:
            logger.warning("[HookEngine] %s took %dms (slow)", point.value, elapsed_ms)

        return context

    def get_registered_points(self) -> List[str]:
        """List hook points that have at least one handler."""
        return [p.value for p, h in self._handlers.items() if h]

    @property
    def handler_count(self) -> int:
        return sum(len(h) for h in self._handlers.values())
