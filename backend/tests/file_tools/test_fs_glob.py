from __future__ import annotations

import pytest

from app.harness.file_tools.context import ToolContext
from app.harness.file_tools.sandbox import PathSandbox
from app.harness.file_tools.tools.fs_glob import FsGlobInput, FsGlobTool


@pytest.fixture
def ctx(sandbox_dir):
    sb = PathSandbox("p1", base_dir=sandbox_dir)
    sb.write_text("literature/a.md", "a")
    sb.write_text("literature/b.md", "b")
    sb.write_text("literature/sub/c.md", "c")
    sb.write_text("notes/d.md", "d")
    return ToolContext(project_id="p1", sandbox=sb)


class TestFsGlob:
    @pytest.mark.asyncio
    async def test_glob_top_level_md(self, ctx) -> None:
        tool = FsGlobTool()
        out = await tool.call(FsGlobInput(pattern="literature/*.md"), ctx)
        assert sorted(out.files) == ["literature/a.md", "literature/b.md"]
        assert out.total == 2

    @pytest.mark.asyncio
    async def test_glob_recursive(self, ctx) -> None:
        tool = FsGlobTool()
        out = await tool.call(FsGlobInput(pattern="literature/**/*.md"), ctx)
        assert "literature/sub/c.md" in out.files

    @pytest.mark.asyncio
    async def test_glob_empty(self, ctx) -> None:
        tool = FsGlobTool()
        out = await tool.call(FsGlobInput(pattern="missing/*.md"), ctx)
        assert out.files == []
        assert out.total == 0

    @pytest.mark.asyncio
    async def test_glob_respects_limit(self, ctx) -> None:
        tool = FsGlobTool()
        out = await tool.call(FsGlobInput(pattern="literature/*.md", limit=1), ctx)
        assert out.total == 1
