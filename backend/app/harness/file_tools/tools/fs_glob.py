from __future__ import annotations

from pydantic import BaseModel

from ..context import ToolContext
from ..registry import FileTool


class FsGlobInput(BaseModel):
    pattern: str
    limit: int = 200


class FsGlobOutput(BaseModel):
    files: list[str]
    total: int


class FsGlobTool(FileTool):
    name = "fs_glob"
    input_model = FsGlobInput
    output_model = FsGlobOutput
    is_read_only = True
    is_concurrency_safe = True

    async def call(self, inp: FsGlobInput, ctx: ToolContext) -> FsGlobOutput:
        matches = ctx.sandbox.glob(inp.pattern)[: inp.limit]
        base = ctx.sandbox.base_dir
        rel = [
            str(p.relative_to(base)).replace("\\", "/") for p in matches
        ]
        return FsGlobOutput(files=rel, total=len(rel))
