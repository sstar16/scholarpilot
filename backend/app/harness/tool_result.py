"""
Standardized tool execution result wrapper.
Wraps the (source_id, List[Dict]) tuple from safe_fetch() with execution metadata.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ToolResult:
    """Immutable result of a single tool (fetcher) invocation."""
    tool_id: str
    success: bool
    docs: List[Dict] = field(default_factory=list)
    execution_ms: int = 0
    error_message: Optional[str] = None
    doc_count: int = 0

    def __post_init__(self):
        # frozen=True 时用 object.__setattr__ 设置派生字段
        if self.doc_count == 0 and self.docs:
            object.__setattr__(self, "doc_count", len(self.docs))
