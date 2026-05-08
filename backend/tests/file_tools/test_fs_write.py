from __future__ import annotations

import pytest

from app.harness.file_tools.context import ToolContext
from app.harness.file_tools.errors import SandboxError
from app.harness.file_tools.sandbox import PathSandbox
from app.harness.file_tools.tools.fs_write import FsWriteInput, FsWriteTool


@pytest.fixture
def ctx(sandbox_dir):
    sb = PathSandbox("p1", base_dir=sandbox_dir)
    return ToolContext(project_id="p1", sandbox=sb)


class TestFsWrite:
    @pytest.mark.asyncio
    async def test_create_new_file(self, ctx) -> None:
        tool = FsWriteTool()
        out = await tool.call(
            FsWriteInput(path="literature/x.md", content="hello"),
            ctx,
        )
        assert out.created is True
        assert out.bytes_written == 5
        assert ctx.sandbox.read_text("literature/x.md") == "hello"

    @pytest.mark.asyncio
    async def test_overwrite_existing(self, ctx) -> None:
        ctx.sandbox.write_text("a.md", "old")
        tool = FsWriteTool()
        out = await tool.call(FsWriteInput(path="a.md", content="new"), ctx)
        assert out.created is False
        assert ctx.sandbox.read_text("a.md") == "new"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, ctx) -> None:
        tool = FsWriteTool()
        await tool.call(
            FsWriteInput(path="deep/nested/a.md", content="x"),
            ctx,
        )
        assert ctx.sandbox.exists("deep/nested/a.md")

    @pytest.mark.asyncio
    async def test_write_rejects_escape(self, ctx) -> None:
        tool = FsWriteTool()
        with pytest.raises(SandboxError):
            await tool.call(
                FsWriteInput(path="../escape.md", content="x"),
                ctx,
            )

    @pytest.mark.asyncio
    async def test_utf8_cjk(self, ctx) -> None:
        tool = FsWriteTool()
        out = await tool.call(
            FsWriteInput(path="cjk.md", content="你好,世界 🌏"),
            ctx,
        )
        assert out.bytes_written == len("你好,世界 🌏".encode("utf-8"))
        assert ctx.sandbox.read_text("cjk.md") == "你好,世界 🌏"
