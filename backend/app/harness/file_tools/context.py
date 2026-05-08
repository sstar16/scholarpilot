from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from .sandbox import PathSandbox


class ToolContext(BaseModel):
    """Per-invocation context passed to every FileTool.call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_id: str
    user_id: Optional[str] = None
    sandbox: PathSandbox
    db_session: Any = None


ToolContext.model_rebuild()
