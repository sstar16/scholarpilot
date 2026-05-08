"""MarkdownSkillExecutor: SkillRegistry 调 .execute(skill_id, context) 时由它处理.

这是 markdown skill 的"运行时": 接收 (base_system_prompt, hook_point, extras) 上下文,
按 persona_role 把 skill body 拼到 prompt 上, 返回 injected_prompt。

注意: 这个 executor 本身不调 LLM, 只是个 prompt 拼装器。
真正的 LLM 调用还是上层 ResearchAgent / Summarizer / Scoring 在做。
"""
from __future__ import annotations

import logging
from typing import Any

from app.harness.skills.markdown_loader import MarkdownSkill

logger = logging.getLogger(__name__)


class MarkdownSkillExecutor:
    """通用 executor: skill body 当 prompt 注入物, context 决定怎么用."""

    def __init__(self, skill: MarkdownSkill):
        self.skill = skill

    async def execute(self, context: dict) -> dict:
        """SkillRegistry.execute() 的实际处理.

        context 至少包含:
        - hook_point: str            (e.g. 'collab_respond' / 'summary' / 'scoring')
        - base_system_prompt: str
        - extras: dict (自由元数据, 可选)

        返回:
        {
            "injected_prompt": str,   # 新的 system prompt (拼上 body 后)
            "skill_applied": bool,    # 是否真的注入了 (hook_point 匹配 → True)
            "skill_name": str,
            "persona_role": str,
            "reason": str,
        }
        """
        hook_point = str(context.get("hook_point") or "").strip()
        base_prompt = str(context.get("base_system_prompt") or "")

        # hook_points 列表为 ['*'] 表示无差别匹配 (留个口子, 谨慎使用)
        accepts_all = "*" in self.skill.hook_points
        if not accepts_all and hook_point and hook_point not in self.skill.hook_points:
            return {
                "injected_prompt": base_prompt,
                "skill_applied": False,
                "skill_name": self.skill.name,
                "persona_role": self.skill.persona_role,
                "reason": f"hook_point '{hook_point}' 不在 skill hook_points={self.skill.hook_points}",
            }

        injected = self._compose(base_prompt, self.skill.body, self.skill.persona_role)
        logger.info(
            "[MarkdownSkillExecutor] '%s' 注入到 hook=%s (role=%s, +%d 字符)",
            self.skill.name, hook_point or "?", self.skill.persona_role,
            len(injected) - len(base_prompt),
        )
        return {
            "injected_prompt": injected,
            "skill_applied": True,
            "skill_name": self.skill.name,
            "persona_role": self.skill.persona_role,
            "reason": f"hook '{hook_point}' matched skill '{self.skill.name}'",
        }

    @staticmethod
    def _compose(base: str, body: str, role: str) -> str:
        """按 role 把 body 拼到 base 前后."""
        body = body.strip()
        base = base.strip()
        if not body:
            return base
        if not base:
            return body
        sep = "\n\n---\n\n"
        if role == "system_suffix":
            return f"{base}{sep}# 额外研究风格指引\n\n{body}"
        # default: system_prefix
        return f"# 研究风格指引（先读这个再看下面）\n\n{body}{sep}{base}"
