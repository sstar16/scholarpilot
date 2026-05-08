"""Prompt 注入辅助: 一行调用决定本次 LLM 调用要不要注入 markdown skill.

为什么不直接走 SkillRegistry.execute？
- registry.execute 的语义是"运行一个工作流"; markdown skill 只是改 prompt, 不需要那一套
- 这里直接读 markdown_loader._LOADED_SKILLS 拿 body, 然后用 MarkdownSkillExecutor 拼
- 维持单一信任源: SkillRegistry 仍然有它们的 SkillDefinition (供前端 list_available)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.harness.skills.markdown_executor import MarkdownSkillExecutor
from app.harness.skills.markdown_loader import (
    MarkdownSkill,
    get_loaded_skills,
    get_skill,
)

logger = logging.getLogger(__name__)


def _match_by_triggers(
    text: str,
    hook_point: str,
    skills: dict[str, MarkdownSkill],
) -> Optional[MarkdownSkill]:
    """text 命中哪些 skill 的 triggers + 适用 hook_point, 取 priority 最高的."""
    if not text:
        return None
    text_low = text.lower()
    matched: list[MarkdownSkill] = []
    for skill in skills.values():
        if hook_point and "*" not in skill.hook_points and hook_point not in skill.hook_points:
            continue
        for trig in skill.triggers:
            if not trig:
                continue
            if trig.lower() in text_low:
                matched.append(skill)
                break
    if not matched:
        return None
    matched.sort(key=lambda s: (-s.priority, s.name))
    return matched[0]


def _explicit_skill(skill_id: Optional[str], hook_point: str) -> Optional[MarkdownSkill]:
    if not skill_id:
        return None
    skill = get_skill(skill_id)
    if not skill:
        logger.info("[skill_injector] explicit_skill_id='%s' 未注册, 忽略", skill_id)
        return None
    if hook_point and "*" not in skill.hook_points and hook_point not in skill.hook_points:
        logger.info(
            "[skill_injector] '%s' 不适用 hook_point=%s (declared %s), 忽略",
            skill_id, hook_point, skill.hook_points,
        )
        return None
    return skill


async def maybe_inject_skill(
    base_system_prompt: str,
    hook_point: str,
    *,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    explicit_skill_id: Optional[str] = None,
    triggers_seen: Optional[list[str]] = None,
    extras: Optional[dict] = None,
) -> tuple[str, dict]:
    """决定是否注入 skill, 返回 (final_system_prompt, debug_info).

    优先级:
    1. explicit_skill_id 显式指定 → 一定用它 (若存在且适用 hook_point)
    2. triggers_seen 命中某 skill 的 triggers → 用它 (多个匹配按 priority desc 取首)
    3. 都没命中 → 返回原 prompt 不变

    Args:
        base_system_prompt: 原 system prompt, 注入后的 prompt 作为返回
        hook_point: 'planning' / 'collab_respond' / 'scoring' / 'summary' / 任意自定义
        project_id / user_id: 留作未来按用户/项目级别筛 skill 的钩子, 当前未用
        explicit_skill_id: 用户在前端选了某个 skill (优先级最高)
        triggers_seen: 用户输入文本 / 关键词列表, 用于自动匹配
        extras: 透传给 executor 的元数据

    Returns:
        (final_system_prompt, debug_info)
        debug_info = {applied: bool, skill_name: str|None, reason: str, persona_role: str|None}
    """
    skills = get_loaded_skills()
    if not skills:
        return base_system_prompt, {
            "applied": False,
            "skill_name": None,
            "reason": "no markdown skills loaded",
            "persona_role": None,
        }

    # ── 优先级 1: 显式指定 ──
    chosen = _explicit_skill(explicit_skill_id, hook_point)
    selection_reason = "explicit_skill_id"

    # ── 优先级 2: trigger 命中 ──
    if not chosen:
        text_blob = " ".join(triggers_seen or [])
        if text_blob:
            chosen = _match_by_triggers(text_blob, hook_point, skills)
            if chosen:
                selection_reason = "triggers_matched"

    if not chosen:
        return base_system_prompt, {
            "applied": False,
            "skill_name": None,
            "reason": "no skill selected (no explicit id, no trigger match)",
            "persona_role": None,
        }

    # ── 实际注入 ──
    executor = MarkdownSkillExecutor(chosen)
    result = await executor.execute({
        "hook_point": hook_point,
        "base_system_prompt": base_system_prompt,
        "extras": extras or {},
    })

    if not result.get("skill_applied"):
        # executor 自己 veto 了 (hook_point 不匹配, 理论上前面已挡掉, 防御一下)
        return base_system_prompt, {
            "applied": False,
            "skill_name": chosen.name,
            "reason": result.get("reason") or "executor declined",
            "persona_role": chosen.persona_role,
        }

    return result["injected_prompt"], {
        "applied": True,
        "skill_name": chosen.name,
        "reason": f"{selection_reason}; {result.get('reason', '')}",
        "persona_role": chosen.persona_role,
    }
