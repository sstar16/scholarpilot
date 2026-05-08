from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel

from app.harness.file_tools.context import ToolContext
from app.harness.file_tools.registry import (
    FileTool,
    PermissionDecision,
    ToolRegistry,
)
from app.harness.file_tools.sandbox import PathSandbox


class DummyInput(BaseModel):
    value: str


class DummyOutput(BaseModel):
    echoed: str


class DummyTool(FileTool):
    name = "dummy"
    input_model = DummyInput
    output_model = DummyOutput
    is_read_only = True
    is_concurrency_safe = True

    async def call(self, inp: DummyInput, ctx: ToolContext) -> DummyOutput:
        return DummyOutput(echoed=inp.value)


class TestToolRegistry:
    def test_register_and_find(self) -> None:
        reg = ToolRegistry()
        tool = DummyTool()
        reg.register(tool)
        assert reg.find("dummy") is tool

    def test_find_missing_returns_none(self) -> None:
        reg = ToolRegistry()
        assert reg.find("nope") is None

    def test_duplicate_register_raises(self) -> None:
        reg = ToolRegistry()
        reg.register(DummyTool())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(DummyTool())

    def test_available_lists_all(self) -> None:
        reg = ToolRegistry()
        reg.register(DummyTool())
        assert "dummy" in reg.available()

    @pytest.mark.asyncio
    async def test_default_permission_allow(self, sandbox_dir) -> None:
        tool = DummyTool()
        sb = PathSandbox("p1", base_dir=sandbox_dir)
        ctx = ToolContext(project_id="p1", sandbox=sb)
        decision = await tool.check_permissions(DummyInput(value="x"), ctx)
        assert decision.behavior == "allow"

    @pytest.mark.asyncio
    async def test_call_passes_through(self, sandbox_dir) -> None:
        tool = DummyTool()
        sb = PathSandbox("p1", base_dir=sandbox_dir)
        ctx = ToolContext(project_id="p1", sandbox=sb)
        result = await tool.call(DummyInput(value="hi"), ctx)
        assert result.echoed == "hi"
