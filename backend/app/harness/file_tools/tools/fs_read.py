from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ..context import ToolContext
from ..registry import FileTool


class FsReadInput(BaseModel):
    path: str
    offset: Optional[int] = None
    limit: Optional[int] = None


class FsReadOutput(BaseModel):
    content: str
    total_lines: int
    truncated: bool


class FsReadTool(FileTool):
    name = "fs_read"
    input_model = FsReadInput
    output_model = FsReadOutput
    is_read_only = True
    is_concurrency_safe = True

    async def call(self, inp: FsReadInput, ctx: ToolContext) -> FsReadOutput:
        text = ctx.sandbox.read_text(inp.path)
        lines = text.splitlines()
        total = len(lines)
        start = inp.offset or 0
        end = start + inp.limit if inp.limit is not None else total
        end = min(end, total)
        segment = "\n".join(lines[start:end])
        return FsReadOutput(
            content=segment,
            total_lines=total,
            truncated=end < total,
        )
