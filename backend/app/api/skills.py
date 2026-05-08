"""
Skills API — list, execute, and retrieve results for harness skills.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillRunRequest(BaseModel):
    document_id: Optional[uuid.UUID] = None  # For deep_dive skill


@router.get("")
async def list_skills(
    current_round: int = 1,
    current_user: User = Depends(get_current_user),
):
    """List available skills for the current round."""
    from app.harness.skill_registry import SkillRegistry
    registry = SkillRegistry.get_instance()
    return {
        "skills": registry.list_available(current_round=current_round),
    }


@router.post("/{project_id}/{skill_id}/run")
async def run_skill(
    project_id: uuid.UUID,
    skill_id: str,
    req: SkillRunRequest = SkillRunRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a skill for a project."""
    from sqlalchemy import select
    from app.models.project import Project
    from app.harness.skill_registry import SkillRegistry

    # Verify project ownership
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    registry = SkillRegistry.get_instance()
    context = {
        "project_id": project_id,
        "user_id": current_user.id,
    }
    if req.document_id:
        context["document_id"] = req.document_id

    skill_result = await registry.execute(skill_id, context)

    if "error" in skill_result and skill_result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=skill_result["error"])

    return skill_result
