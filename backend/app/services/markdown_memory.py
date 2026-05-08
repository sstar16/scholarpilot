"""Markdown 记忆服务 — 双层 .md 机制（学 Claude Code 的 MEMORY 模型）。

- 用户级（UserMemory.markdown_text）：昵称/性别/年龄/职业/研究大方向/通用偏好
  跨项目共享，一个用户一份。
- 项目级（UserProfile.project_markdown）：当前项目的研究方向、子问题、关注点、
  已读过的关键文献。(user_id, project_id) 唯一。

两份都是纯 Markdown，用户可见可手动编辑；也支持 LLM 从对话增补。
检索时拼成 "## 用户身份\n...\n## 当前项目\n..." 一并喂给 QueryPlan/Scoring agent。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_memory import UserMemory
from app.models.user_profile import UserProfile


# —— 默认模板：首次访问时给用户看的空骨架，引导填写 ——

DEFAULT_USER_MARKDOWN = """# 用户档案

> 这份 Markdown 记录你的身份与通用研究偏好，跨项目共享。
> 你可以手动编辑，也可以让 AI 从对话中自动提炼。

## 身份
- **昵称**：
- **职业/身份**：
- **所在机构**：

## 研究大方向
- （例：分布式系统、计算机视觉、蛋白质结构预测……）

## 偏好
- **语言**：
- **文献类型偏好**（论文 / 专利 / 综述 / 临床）：
- **偏爱的数据源**：
"""


DEFAULT_PROJECT_MARKDOWN_TEMPLATE = """# {project_title}

> 本项目的研究方向、关注点与已读重点，仅对此项目生效。

## 研究方向
- （这个项目具体在做什么）

## 核心子问题
-
-

## 关键术语 / 关键词
-

## 已读重点文献 / 思路
-

## 近期关注点
-
"""


# ════════════════════════════════════════════════
# 用户级
# ════════════════════════════════════════════════


async def get_or_create_user_memory(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> UserMemory:
    """取/建用户级记忆。首次访问自动落默认模板。"""
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id)
    )
    mem = result.scalar_one_or_none()
    if mem is None:
        mem = UserMemory(
            user_id=user_id,
            markdown_text=DEFAULT_USER_MARKDOWN,
            version=0,
        )
        db.add(mem)
        await db.flush()
    return mem


async def update_user_memory(
    user_id: uuid.UUID,
    markdown_text: str,
    db: AsyncSession,
) -> UserMemory:
    """用户手动编辑或 LLM 提炼后的整体覆盖。"""
    mem = await get_or_create_user_memory(user_id, db)
    mem.markdown_text = markdown_text or ""
    mem.version += 1
    mem.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return mem


# ════════════════════════════════════════════════
# 项目级
# ════════════════════════════════════════════════


async def get_or_create_project_memory(
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    db: AsyncSession,
    project_title: Optional[str] = None,
) -> UserProfile:
    """取/建项目级记忆（寄生在 UserProfile 上）。首次访问落默认模板。"""
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_id,
            UserProfile.project_id == project_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserProfile(
            user_id=user_id,
            project_id=project_id,
            preferred_keywords=[],
            excluded_keywords=[],
            preferred_sources=[],
            preferred_doc_types=[],
            preferred_authors=[],
            feedback_count=0,
        )
        db.add(profile)
        await db.flush()

    # 首次进入页面时，若 project_markdown 为空则落默认模板
    if not (profile.project_markdown and profile.project_markdown.strip()):
        profile.project_markdown = DEFAULT_PROJECT_MARKDOWN_TEMPLATE.format(
            project_title=project_title or "本项目",
        )
        await db.flush()

    return profile


async def update_project_memory(
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    markdown_text: str,
    db: AsyncSession,
) -> UserProfile:
    """用户手动编辑或 LLM 增补后的整体覆盖。"""
    profile = await get_or_create_project_memory(user_id, project_id, db)
    profile.project_markdown = markdown_text or ""
    profile.last_updated = datetime.now(timezone.utc)
    await db.flush()
    return profile


# ════════════════════════════════════════════════
# 组合（喂给 agents）
# ════════════════════════════════════════════════


async def build_combined_memory_for_agents(
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """把三层 Markdown 拼成一份喂给 QueryPlanAgent / ScoringAgent 的 context。

    约定格式：
        # USER (跨项目共享)
        <user_memory.markdown_text>

        # PROJECT (仅当前项目)
        <user_profile.project_markdown>

        # AUTO_RECIPE (从 4 桶反馈自动归纳，每轮 regenerate)
        <user_profile.auto_recipe_md>

    任一层空白则省略对应块；全空返回空串（上游按无记忆处理）。
    """
    parts: list[str] = []

    user_mem = await db.execute(
        select(UserMemory.markdown_text).where(UserMemory.user_id == user_id)
    )
    user_md = (user_mem.scalar_one_or_none() or "").strip()
    if user_md:
        parts.append("# USER (跨项目共享)\n" + user_md)

    proj_mem = await db.execute(
        select(UserProfile.project_markdown, UserProfile.auto_recipe_md).where(
            UserProfile.user_id == user_id,
            UserProfile.project_id == project_id,
        )
    )
    row = proj_mem.first()
    proj_md = ((row[0] if row else None) or "").strip()
    recipe_md = ((row[1] if row else None) or "").strip()
    if proj_md:
        parts.append("# PROJECT (仅当前项目)\n" + proj_md)
    if recipe_md:
        parts.append("# AUTO_RECIPE (从 4 桶反馈自动归纳)\n" + recipe_md)

    return "\n\n".join(parts)
