from __future__ import annotations

import pytest

from app.harness.file_tools.context import ToolContext
from app.harness.file_tools.sandbox import PathSandbox
from app.harness.file_tools.tools.fs_read import FsReadInput, FsReadTool


@pytest.fixture
def ctx(sandbox_dir):
    sb = PathSandbox("p1", base_dir=sandbox_dir)
    sb.write_text("a.txt", "line1\nline2\nline3\nline4\nline5")
    return ToolContext(project_id="p1", sandbox=sb)


class TestFsRead:
    @pytest.mark.asyncio
    async def test_read_full_file(self, ctx) -> None:
        tool = FsReadTool()
        out = await tool.call(FsReadInput(path="a.txt"), ctx)
        assert "line1" in out.content
        assert "line5" in out.content
        assert out.total_lines == 5
        assert out.truncated is False

    @pytest.mark.asyncio
    async def test_read_with_offset_limit(self, ctx) -> None:
        tool = FsReadTool()
        out = await tool.call(FsReadInput(path="a.txt", offset=1, limit=2), ctx)
        assert out.content == "line2\nline3"
        assert out.total_lines == 5
        assert out.truncated is True

    @pytest.mark.asyncio
    async def test_read_missing_file_raises(self, ctx) -> None:
        tool = FsReadTool()
        with pytest.raises(FileNotFoundError):
            await tool.call(FsReadInput(path="nope.txt"), ctx)
