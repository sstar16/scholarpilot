"""
File tools harness — Claude Code 风格的 sandboxed file access primitives.

S1: PathSandbox + ToolRegistry + fs_read/glob/write, all internal use.
S2: expose via MCP to LLM agents for 共同研究模式.
"""
from .context import ToolContext
from .errors import SandboxError, ToolError
from .registry import FileTool, PermissionDecision, ToolRegistry, tool_registry
from .sandbox import PathSandbox

__all__ = [
    "FileTool",
    "PathSandbox",
    "PermissionDecision",
    "SandboxError",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "tool_registry",
]
