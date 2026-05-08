from __future__ import annotations

from pydantic import BaseModel

from ..context import ToolContext
from ..registry import FileTool


class FsWriteInput(BaseModel):
    path: str
    content: str


class FsWriteOutput(BaseModel):
    path: str
    bytes_written: int
    created: bool


class FsWriteTool(FileTool):
    name = "fs_write"
    input_model = FsWriteInput
    output_model = FsWriteOutput
    is_read_only = False
    is_destructive = False
    is_concurrency_safe = False

    async def call(self, inp: FsWriteInput, ctx: ToolContext) -> FsWriteOutput:
        existed = ctx.sandbox.exists(inp.path)
        ctx.sandbox.write_text(inp.path, inp.content)
        return FsWriteOutput(
            path=inp.path,
            bytes_written=len(inp.content.encode("utf-8")),
            created=not existed,
        )
