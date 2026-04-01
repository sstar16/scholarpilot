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
    """Lifecycle boundaries where hooks can fire."""
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
