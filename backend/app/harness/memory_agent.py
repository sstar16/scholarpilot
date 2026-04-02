"""
Memory Update Agent — 从用户反馈的 4-bucket 文档中学习研究偏好。
替代纯关键词频率的 profile 更新，用 LLM 理解用户真正想要什么。

与现有 profile_service.update_profile_from_feedbacks() 并行运行，互为冗余。
"""
import json
import logging
import re
from typing import Dict, List, Optional

from app.harness.prompts.memory_update import build_memory_update_prompt

logger = logging.getLogger(__name__)


class MemoryAgent:
    """
    LLM-driven user memory updater.
    Takes 4-bucket feedback and produces structured memory text.
    """

    def __init__(self, llm_manager=None):
        self._llm = llm_manager

    async def update_memory(
        self,
        project_description: str,
        current_memory: str,
        memory_version: int,
        feedback_buckets: Dict[int, List[Dict]],
    ) -> Optional[str]:
        """
        根据反馈更新记忆文本。

        Args:
            project_description: 项目描述
            current_memory: 当前 memory_text（可能为空）
            memory_version: 当前版本号
            feedback_buckets: {2: [...], 1: [...], 0: [...], -1: [...]}

        Returns:
            更新后的 memory_text（结构化 markdown），或 None（失败时）
        """
        if not self._llm:
            logger.warning("[MemoryAgent] LLM 不可用，跳过记忆更新")
            return None

        # 如果反馈为空（用户没评分任何文档），不更新
        total_feedback = sum(len(v) for v in feedback_buckets.values())
        if total_feedback == 0:
            return current_memory

        prompt = build_memory_update_prompt(
            project_description=project_description,
            current_memory=current_memory,
            memory_version=memory_version,
            feedback_buckets=feedback_buckets,
        )

        try:
            result = await self._llm.generate(prompt, temperature=0.2)
            if not result:
                logger.warning("[MemoryAgent] LLM 返回空结果")
                return None

            parsed = _parse_memory_response(result)
            if not parsed:
                logger.warning("[MemoryAgent] 解析失败: %s", result[:200])
                return None

            # 转为可读的 markdown 格式
            memory_text = _format_memory_markdown(parsed, memory_version + 1)

            logger.info(
                "[MemoryAgent] 记忆更新成功 v%d → v%d, focus: %s",
                memory_version, memory_version + 1,
                parsed.get("research_focus", "")[:50],
            )
            return memory_text

        except Exception as e:
            logger.warning("[MemoryAgent] 记忆更新异常: %s", e)
            return None


async def run_memory_update(
    user_id,
    project_id,
    project_description: str,
    feedback_dicts: List[Dict],
    llm_manager,
    db,
):
    """
    便捷入口：从 feedback list 构建 4-bucket 并运行 MemoryAgent。
    直接更新 DB 和 Redis。
    """
    from app.models.user_profile import UserProfile
    from sqlalchemy import select

    # 获取当前 profile
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_id,
            UserProfile.project_id == project_id,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return

    # 构建 4-bucket
    buckets: Dict[int, List[Dict]] = {2: [], 1: [], 0: [], -1: []}
    for fd in feedback_dicts:
        rel = fd.get("relevance", 0)
        if rel in buckets:
            buckets[rel].append({
                "title": fd.get("title", ""),
                "one_line_summary": fd.get("one_line_summary", ""),
                "source": fd.get("source", ""),
            })

    agent = MemoryAgent(llm_manager=llm_manager)
    new_memory = await agent.update_memory(
        project_description=project_description,
        current_memory=profile.memory_text or "",
        memory_version=profile.memory_version or 0,
        feedback_buckets=buckets,
    )

    if new_memory:
        profile.memory_text = new_memory
        profile.memory_version = (profile.memory_version or 0) + 1
        await db.flush()

        # 缓存到 Redis
        try:
            import redis.asyncio as aioredis
            from app.config import settings
            r = aioredis.from_url(settings.redis_url)
            await r.set(
                f"memory:{user_id}:{project_id}",
                new_memory,
                ex=86400,  # 24h TTL
            )
            await r.close()
        except Exception as e:
            logger.warning("[MemoryAgent] Redis 缓存失败: %s", e)


def _parse_memory_response(text: str) -> Optional[Dict]:
    """从 LLM 输出解析记忆 JSON"""
    match = re.search(r'\{[^{}]*"research_focus"[^}]*\}', text, re.DOTALL)
    if not match:
        # 尝试更宽泛的 JSON 匹配
        match = re.search(r'\{[\s\S]*?\}', text)
        if not match:
            return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    if "research_focus" not in data:
        return None

    return data


def _format_memory_markdown(data: Dict, version: int) -> str:
    """将解析后的 JSON 转为可读的 markdown 记忆文本"""
    lines = [f"# 研究偏好记忆 v{version}", ""]

    focus = data.get("research_focus", "")
    if focus:
        lines.append(f"## 核心方向\n{focus}\n")

    preferred = data.get("preferred_topics", [])
    if preferred:
        lines.append("## 偏好主题")
        for t in preferred:
            lines.append(f"- {t}")
        lines.append("")

    excluded = data.get("excluded_topics", [])
    if excluded:
        lines.append("## 排除方向")
        for t in excluded:
            lines.append(f"- {t}")
        lines.append("")

    methods = data.get("methodology_preferences", [])
    if methods:
        lines.append("## 方法偏好")
        for m in methods:
            lines.append(f"- {m}")
        lines.append("")

    authors = data.get("key_authors", [])
    if authors:
        lines.append("## 关键作者")
        for a in authors:
            lines.append(f"- {a}")
        lines.append("")

    sources = data.get("source_preferences", [])
    if sources:
        lines.append("## 来源偏好")
        for s in sources:
            lines.append(f"- {s}")
        lines.append("")

    notes = data.get("notes", "")
    if notes:
        lines.append(f"## 备注\n{notes}\n")

    return "\n".join(lines)
