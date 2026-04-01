"""
Tool Registry — unifies FetcherRegistry.SOURCES metadata with live ALL_FETCHERS
instances, adding runtime statistics (latency, reliability).

Adapted from Claude Code's S02 (Tool Dispatch) pattern.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from app.harness.tool_result import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ToolSchema:
    """Combined metadata + runtime stats for a registered tool (data source)."""
    tool_id: str
    name: str
    description: str
    doc_type: str           # paper / preprint / patent / clinical_trial
    category: str           # literature / patents / clinical
    language: str           # en / zh / multilingual
    phase: int              # 1 = available, 2 = planned
    enabled: bool = True

    # Runtime statistics (updated after each invocation)
    total_invocations: int = 0
    successful_invocations: int = 0
    total_latency_ms: int = 0

    @property
    def avg_latency_ms(self) -> int:
        if self.successful_invocations == 0:
            return 0
        return self.total_latency_ms // self.successful_invocations

    @property
    def reliability(self) -> float:
        """Success rate 0.0 - 1.0. Returns 1.0 if never invoked (optimistic default)."""
        if self.total_invocations == 0:
            return 1.0
        return self.successful_invocations / self.total_invocations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "doc_type": self.doc_type,
            "category": self.category,
            "language": self.language,
            "phase": self.phase,
            "enabled": self.enabled,
            "total_invocations": self.total_invocations,
            "successful_invocations": self.successful_invocations,
            "avg_latency_ms": self.avg_latency_ms,
            "reliability": round(self.reliability, 3),
        }


class ToolRegistry:
    """
    Singleton registry of all data source tools.
    Wraps existing fetchers without replacing them.
    """

    _instance: Optional["ToolRegistry"] = None

    def __init__(self):
        self._tools: Dict[str, ToolSchema] = {}
        self._fetchers: Dict[str, Any] = {}  # source_id -> AbstractFetcher instance

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton (for testing)."""
        cls._instance = None

    def register(self, tool_id: str, metadata: Dict, fetcher=None) -> None:
        """Register a tool from FetcherRegistry metadata + optional live fetcher."""
        schema = ToolSchema(
            tool_id=tool_id,
            name=metadata.get("name", tool_id),
            description=metadata.get("description", ""),
            doc_type=metadata.get("doc_type", "paper"),
            category=metadata.get("category", "literature"),
            language=metadata.get("language", "en"),
            phase=metadata.get("phase", 1),
            enabled=fetcher is not None,
        )
        self._tools[tool_id] = schema
        if fetcher:
            self._fetchers[tool_id] = fetcher

    def get_tool(self, tool_id: str) -> Optional[ToolSchema]:
        return self._tools.get(tool_id)

    def get_fetcher(self, tool_id: str):
        return self._fetchers.get(tool_id)

    def get_available_tools(
        self,
        category: Optional[str] = None,
        language: Optional[str] = None,
        enabled_only: bool = True,
    ) -> List[ToolSchema]:
        """Filter tools by criteria."""
        result = []
        for tool in self._tools.values():
            if enabled_only and not tool.enabled:
                continue
            if category and tool.category != category:
                continue
            if language and tool.language != language:
                continue
            result.append(tool)
        return result

    def record_result(self, tool_id: str, success: bool, latency_ms: int) -> None:
        """Record execution statistics for a tool."""
        tool = self._tools.get(tool_id)
        if not tool:
            return
        tool.total_invocations += 1
        if success:
            tool.successful_invocations += 1
            tool.total_latency_ms += latency_ms

    def get_all_stats(self) -> List[Dict]:
        """Return stats for all registered tools (for /health endpoint)."""
        return [t.to_dict() for t in self._tools.values()]

    def get_reliability_report(self) -> Dict[str, float]:
        """Return tool_id -> reliability mapping (for agent planning context)."""
        return {
            t.tool_id: t.reliability
            for t in self._tools.values()
            if t.enabled
        }

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def enabled_count(self) -> int:
        return sum(1 for t in self._tools.values() if t.enabled)


def init_tool_registry() -> ToolRegistry:
    """
    Initialize the global tool registry from existing FetcherRegistry + ALL_FETCHERS.
    Called once at app startup (FastAPI lifespan).
    """
    from app.services.fetchers.base import FetcherRegistry
    from app.services.fetchers.international import ALL_FETCHERS

    registry = ToolRegistry.get_instance()

    # Register all known sources (including disabled/planned ones)
    for source_id, metadata in FetcherRegistry.SOURCES.items():
        fetcher = ALL_FETCHERS.get(source_id)
        registry.register(source_id, metadata, fetcher=fetcher)

    logger.info(
        "[ToolRegistry] 已注册 %d 个工具（%d 个可用）",
        registry.tool_count,
        registry.enabled_count,
    )
    return registry
