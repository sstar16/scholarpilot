"""Memory Markdown Agent — 从对话增量提炼 .md 记忆。

两个入口：
- refine_user_markdown: 用户级（身份/职业/研究大方向/偏好）
- refine_project_markdown: 项目级（本项目研究方向/子问题/关注点）

设计要点：
- **绝不**自己编造用户没说过的内容；只整理/归并 LLM 从对话中看到的线索
- 保留用户已手写的 section；只对"空占位"或"已有条目"做增补
- 失败或 LLM 不可用时，静默返回 `current_markdown` 不动（前端按原值呈现）
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.core.llm_config_store import get_llm_manager

logger = logging.getLogger(__name__)


_USER_PROMPT_TEMPLATE = """你是一个记忆整理助手。阅读下方"当前记忆 Markdown"与"最近对话"，
只根据对话中用户明确说过的信息，补全或修订这份用户级 Markdown。

【硬性规则】
1. 仅使用对话中**用户本人**提到的身份/职业/研究大方向/偏好；**禁止编造**、
   禁止从"学科词汇"猜职业/机构，禁止引入与用户无关的研究主题。
2. 保留原 Markdown 的结构与用户已手写的内容；只在空占位或已有列表里增补。
3. 不要把"当前项目"里的具体研究方向（如某篇论文、某个子问题）写入用户级 —— 那是项目级的事。
4. 用户级只写稳定身份：昵称、性别（仅当明确）、年龄/年级（仅当明确）、职业/学生/研究员、
   所在机构、常用语言、研究大方向（如"计算机系统/机器学习/生物信息"）、数据源偏好。
5. 返回**完整**的新 Markdown（而非 diff），保持 UTF-8、中文书写、Markdown 语法合法。
6. 如果对话里没有任何新信息能增补，**原样返回** 当前 Markdown，一字不改。

【当前用户】{user_name}

【当前记忆 Markdown】
{current_markdown}

【最近对话】
{conversation}

【输出】
只输出新的 Markdown 本体，不要包含 ``` 代码块围栏、不要前后解释。
"""


_PROJECT_PROMPT_TEMPLATE = """你是一个项目研究记忆整理助手。阅读"当前项目记忆 Markdown"与"项目内对话"，
只根据对话中用户明确表达的研究方向/子问题/关注点，补全或修订这份项目级 Markdown。

【硬性规则】
1. 仅写对话中出现的本项目研究方向、核心子问题、关键术语、用户关注的文献/思路、近期关注点。
2. **禁止**引入对话中完全没出现的领域词（反污染：不要把别的学科词写进来）。
3. 保留用户手写部分；只在空占位或已有列表里增补。
4. 不要把用户身份/职业（那属于用户级）写入项目级。
5. 返回**完整**的新 Markdown。
6. 如无新信息，**原样返回**。

【项目标题】{project_title}

【当前项目记忆 Markdown】
{current_markdown}

【项目内对话】
{conversation}

【输出】
只输出新的 Markdown 本体，不要代码块围栏、不要前后解释。
"""


def _format_conversation(messages: list[dict]) -> str:
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        tag = {"user": "用户", "assistant": "AI", "system": "系统"}.get(role, role)
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{tag}] {content}")
    return "\n\n".join(lines) if lines else "(无对话)"


async def _call_llm(prompt: str) -> Optional[str]:
    try:
        llm = await get_llm_manager()
        result = await llm.generate(prompt, temperature=0.1, max_tokens=3000)
        return (result or "").strip() or None
    except Exception as e:
        logger.warning("memory_markdown_agent LLM call failed: %s", e)
        return None


async def refine_user_markdown(
    current_markdown: str,
    messages: list[dict],
    user_name: Optional[str] = None,
) -> str:
    prompt = _USER_PROMPT_TEMPLATE.format(
        user_name=user_name or "(匿名)",
        current_markdown=current_markdown.strip() or "(空)",
        conversation=_format_conversation(messages),
    )
    new_md = await _call_llm(prompt)
    if not new_md:
        return current_markdown
    # 防御：LLM 如果偷懒返回代码围栏/解释，剥离掉
    return _strip_code_fence(new_md)


async def refine_project_markdown(
    current_markdown: str,
    messages: list[dict],
    project_title: Optional[str] = None,
) -> str:
    prompt = _PROJECT_PROMPT_TEMPLATE.format(
        project_title=project_title or "本项目",
        current_markdown=current_markdown.strip() or "(空)",
        conversation=_format_conversation(messages),
    )
    new_md = await _call_llm(prompt)
    if not new_md:
        return current_markdown
    return _strip_code_fence(new_md)


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        # 去掉第一行 ```xxx 和最后一行 ```
        if lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        t = "\n".join(lines).strip()
    return t
