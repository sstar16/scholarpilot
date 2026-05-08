"""客户端 telemetry sink — sp-api 版。

只接受 services.telemetry.KNOWN_EVENTS 里登记过的事件。
sp-api 没有 project FK 表，project_id 是客户端 UUID 字符串。
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_current_user
from app.models.user import User
from app.services.telemetry import KNOWN_EVENTS, emit

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class TelemetryEvent(BaseModel):
    event: str = Field(..., min_length=1, max_length=64)
    project_id: UUID | None = None
    properties: dict[str, Any] | None = None


@router.post("", status_code=204)
async def post_telemetry(
    body: TelemetryEvent,
    current_user: User = Depends(get_current_user),
):
    if body.event not in KNOWN_EVENTS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown event '{body.event}' — register in "
                   f"services.telemetry.KNOWN_EVENTS first",
        )
    fields: dict[str, Any] = {"user_id": current_user.id}
    if body.project_id:
        fields["project_id"] = body.project_id
    if body.properties:
        fields.update(body.properties)
    emit(body.event, **fields)
