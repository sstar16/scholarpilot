from __future__ import annotations

from typing import ClassVar, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel

from .context import ToolContext

Input = TypeVar("Input", bound=BaseModel)
Output = TypeVar("Output", bound=BaseModel)


class PermissionDecision(BaseModel):
    behavior: Literal["allow", "deny", "ask"]
    message: Optional[str] = None


class FileTool(Generic[Input, Output]):
    """Abstract base for sandboxed file operations.

    Claude Code 风格的 buildTool 抽象,在 S2 会注入 check_permissions 的策略,
    暴露 MCP 给 LLM agent。S1 内部调用默认全 allow。
    """

    name: ClassVar[str] = ""
    input_model: ClassVar[type[BaseModel]] = BaseModel
    output_model: ClassVar[type[BaseModel]] = BaseModel
    is_read_only: ClassVar[bool] = False
    is_concurrency_safe: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = False

    async def check_permissions(
        self, inp: BaseModel, ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def call(self, inp: BaseModel, ctx: ToolContext) -> BaseModel:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, FileTool] = {}

    def register(self, tool: FileTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def find(self, name: str) -> Optional[FileTool]:
        return self._tools.get(name)

    def available(self, mode: str = "default") -> list[str]:
        return list(self._tools.keys())


_registry: Optional[ToolRegistry] = None


def tool_registry() -> ToolRegistry:
    """Global lazy singleton. Registers all S1 tools on first call."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        from .tools.fs_read import FsReadTool
        from .tools.fs_glob import FsGlobTool
        from .tools.fs_write import FsWriteTool
        _registry.register(FsReadTool())
        _registry.register(FsGlobTool())
        _registry.register(FsWriteTool())
    return _registry
