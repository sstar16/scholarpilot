"""ProjectSceneResolver — 3 场景判定（FRESH / EMPTY_LIBRARY / HAS_LIBRARY）。

场景：
- FRESH: project.current_round == 0
- EMPTY_LIBRARY: 跑过轮次但文献库空
- HAS_LIBRARY: 跑过轮次且有文献（检索 OR 手动上传 OR 分类）
"""
from __future__ import annotations

import logging
import uuid
from enum import Enum

from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_classification import DocumentClassification
from app.models.project import Project
from app.models.round_document import RoundDocument
from app.models.search_round import SearchRound

logger = logging.getLogger(__name__)


class ProjectScene(str, Enum):
    FRESH = "fresh"
    EMPTY_LIBRARY = "empty"
    HAS_LIBRARY = "has_lib"


async def resolve_scene(project_id: uuid.UUID, db: AsyncSession) -> ProjectScene:
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project not found: {project_id}")
    if project.current_round == 0:
        return ProjectScene.FRESH

    # RoundDocument has no project_id; reach it via SearchRound join
    rd_q = (
        select(RoundDocument.document_id)
        .join(SearchRound, RoundDocument.round_id == SearchRound.id)
        .where(SearchRound.project_id == project_id)
    )
    dc_q = select(DocumentClassification.document_id).where(
        DocumentClassification.project_id == project_id
    )
    count = await db.scalar(
        select(func.count()).select_from(union(rd_q, dc_q).subquery())
    )
    return ProjectScene.HAS_LIBRARY if (count or 0) > 0 else ProjectScene.EMPTY_LIBRARY
