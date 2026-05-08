"""features router — 功能准入触发 + 4 按钮批量校验。"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.feature_gate import FEATURES, check, check_all

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects/{project_id}/features", tags=["features"])


class TriggerRequest(BaseModel):
    feature: str
    session_id: uuid.UUID


class TriggerResponse(BaseModel):
    allowed: bool
    rich_message: dict


class CheckAllResponse(BaseModel):
    new_round: dict
    collaboration: dict
    schedule: dict
    pdf_import: dict


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_feature(
    project_id: uuid.UUID,
    req: TriggerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.feature not in FEATURES:
        raise HTTPException(status_code=400, detail=f"unknown feature: {req.feature}")
    result = await check(req.feature, project_id, db)
    if result.allowed:
        rich: dict = {
            "rich_type": "feature_gate_allowed",
            "feature": req.feature,
            "scene": result.scene,
            "next_hint": f"请在对话中继续 {req.feature} 流程",
        }
    else:
        rich = {
            "rich_type": "feature_gate_blocked",
            "feature": req.feature,
            "scene": result.scene,
            "reason": result.reason,
            "suggested_action": result.suggested_action,
        }
    return TriggerResponse(allowed=result.allowed, rich_message=rich)


@router.get("/check-all", response_model=CheckAllResponse)
async def check_all_features(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    results = await check_all(project_id, db)
    return CheckAllResponse(
        new_round=asdict(results["new_round"]),
        collaboration=asdict(results["collaboration"]),
        schedule=asdict(results["schedule"]),
        pdf_import=asdict(results["pdf_import"]),
    )
