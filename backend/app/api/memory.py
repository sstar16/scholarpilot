"""Markdown 记忆 API —— 用户级 + 项目级双层（学 Claude Code MEMORY 机制）。

路由：
  GET    /api/memory/user                        → 读取用户级 .md
  PUT    /api/memory/user                        → 用户手动覆写
  POST   /api/memory/user/extract-from-chat      → LLM 从最近对话增补
  GET    /api/memory/project/{project_id}        → 读取项目级 .md
  PUT    /api/memory/project/{project_id}        → 用户手动覆写
  POST   /api/memory/project/{project_id}/extract-from-chat  → LLM 从对话增补

对话消息来源：ConversationSession.messages（JSON 数组），取最近 40 条。
LLM 调用走全局 get_llm_manager()，失败静默返回原 markdown。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.conversation_session import ConversationSession
from app.services.markdown_memory import (
    get_or_create_user_memory,
    update_user_memory,
    get_or_create_project_memory,
    update_project_memory,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ──────────── Schemas ────────────


class MemoryOut(BaseModel):
    scope: str  # "user" | "project"
    markdown_text: str
    version: Optional[int] = None
    updated_at: Optional[datetime] = None


class MemoryUpdate(BaseModel):
    markdown_text: str = Field(max_length=40000)


# ──────────── 用户级 ────────────


@router.get("/user", response_model=MemoryOut)
async def get_user_memory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    mem = await get_or_create_user_memory(user.id, db)
    await db.commit()
    return MemoryOut(
        scope="user",
        markdown_text=mem.markdown_text,
        version=mem.version,
        updated_at=mem.updated_at,
    )


@router.put("/user", response_model=MemoryOut)
async def put_user_memory(
    body: MemoryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    mem = await update_user_memory(user.id, body.markdown_text, db)
    await db.commit()
    return MemoryOut(
        scope="user",
        markdown_text=mem.markdown_text,
        version=mem.version,
        updated_at=mem.updated_at,
    )


@router.post("/user/extract-from-chat", response_model=MemoryOut)
async def extract_user_memory_from_chat(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取用户最近所有项目的最近 session 对话（合 40 条），LLM 增量提炼到用户级 .md。"""
    from app.harness.agents.memory_markdown_agent import refine_user_markdown

    mem = await get_or_create_user_memory(user.id, db)
    messages = await _collect_recent_user_messages(user.id, db, limit=40)
    if not messages:
        await db.commit()
        return MemoryOut(scope="user", markdown_text=mem.markdown_text,
                         version=mem.version, updated_at=mem.updated_at)

    new_md = await refine_user_markdown(
        current_markdown=mem.markdown_text,
        messages=messages,
        user_name=user.name,
    )
    mem = await update_user_memory(user.id, new_md, db)
    await db.commit()
    return MemoryOut(scope="user", markdown_text=mem.markdown_text,
                     version=mem.version, updated_at=mem.updated_at)


# ──────────── 项目级 ────────────


async def _require_project(
    project_id: uuid.UUID, user: User, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在或无访问权限")
    return project


@router.get("/project/{project_id}", response_model=MemoryOut)
async def get_project_memory(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _require_project(project_id, user, db)
    profile = await get_or_create_project_memory(
        user.id, project_id, db, project_title=project.title
    )
    await db.commit()
    return MemoryOut(
        scope="project",
        markdown_text=profile.project_markdown or "",
        updated_at=profile.last_updated,
    )


@router.put("/project/{project_id}", response_model=MemoryOut)
async def put_project_memory(
    project_id: uuid.UUID,
    body: MemoryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project(project_id, user, db)
    profile = await update_project_memory(user.id, project_id, body.markdown_text, db)
    await db.commit()
    return MemoryOut(
        scope="project",
        markdown_text=profile.project_markdown or "",
        updated_at=profile.last_updated,
    )


@router.get("/project/{project_id}/recipe")
async def get_project_recipe(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """读取自动生成的项目食谱（read-only）+ 上次更新时间。"""
    from sqlalchemy import select
    from app.models.user_profile import UserProfile

    await _require_project(project_id, user, db)
    res = await db.execute(
        select(UserProfile.auto_recipe_md, UserProfile.recipe_updated_at)
        .where(
            UserProfile.user_id == user.id,
            UserProfile.project_id == project_id,
        )
    )
    row = res.first()
    return {
        "scope": "recipe",
        "markdown_text": (row[0] if row else None) or "",
        "updated_at": row[1].isoformat() if row and row[1] else None,
    }


@router.post("/project/{project_id}/recipe/regenerate")
async def regenerate_project_recipe_endpoint(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发食谱重新生成（用户在 Memory 页点强制 regen 按钮）。"""
    from app.services.project_recipe import regenerate_project_recipe
    await _require_project(project_id, user, db)
    md, stats = await regenerate_project_recipe(
        project_id=project_id, user_id=user.id, db=db,
    )
    return {
        "scope": "recipe",
        "markdown_text": md,
        "updated_at": None,
        "stats": {
            "total_classified": stats.total_classified,
            "bucket_counts": stats.bucket_counts,
        },
    }


@router.post("/project/{project_id}/extract-from-chat", response_model=MemoryOut)
async def extract_project_memory_from_chat(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.harness.agents.memory_markdown_agent import refine_project_markdown

    project = await _require_project(project_id, user, db)
    profile = await get_or_create_project_memory(
        user.id, project_id, db, project_title=project.title
    )
    messages = await _collect_project_messages(project_id, db, limit=40)
    if not messages:
        await db.commit()
        return MemoryOut(scope="project", markdown_text=profile.project_markdown or "",
                         updated_at=profile.last_updated)

    new_md = await refine_project_markdown(
        current_markdown=profile.project_markdown or "",
        messages=messages,
        project_title=project.title,
    )
    profile = await update_project_memory(user.id, project_id, new_md, db)
    await db.commit()
    return MemoryOut(scope="project", markdown_text=profile.project_markdown or "",
                     updated_at=profile.last_updated)


# ──────────── 消息收集 helper ────────────


async def _collect_project_messages(
    project_id: uuid.UUID, db: AsyncSession, limit: int = 40
) -> list[dict]:
    result = await db.execute(
        select(ConversationSession.messages).where(
            ConversationSession.project_id == project_id
        )
    )
    all_msgs: list[dict] = []
    for row in result.scalars().all():
        if not row:
            continue
        for m in row:
            if isinstance(m, dict) and m.get("content"):
                all_msgs.append({
                    "role": m.get("role", "user"),
                    "content": str(m.get("content", ""))[:2000],
                })
    return all_msgs[-limit:]


async def _collect_recent_user_messages(
    user_id: uuid.UUID, db: AsyncSession, limit: int = 40
) -> list[dict]:
    """扫用户所有项目的 session，取最近 limit 条（按更新时间降序合并后截断）。"""
    result = await db.execute(
        select(ConversationSession.messages, ConversationSession.updated_at)
        .join(Project, ConversationSession.project_id == Project.id)
        .where(Project.user_id == user_id)
        .order_by(ConversationSession.updated_at.desc())
        .limit(5)
    )
    all_msgs: list[dict] = []
    for messages, _ in result.all():
        if not messages:
            continue
        for m in messages:
            if isinstance(m, dict) and m.get("content"):
                all_msgs.append({
                    "role": m.get("role", "user"),
                    "content": str(m.get("content", ""))[:2000],
                })
    return all_msgs[-limit:]
