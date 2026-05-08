"""
IntentAnalysis Agent — 自然语言意图解析。
从用户自由文本中提取结构化的研究意图，自动生成项目配置。
LLM 不可用时 returns None → 调用方回退到手动表单。
"""
import json
import logging
import random
import re
from typing import Optional

from app.harness.prompts.intent_analysis import build_intent_prompt

logger = logging.getLogger(__name__)

# 有效值集合
VALID_DOMAINS = {
    "biology", "chemistry", "physics", "medicine", "engineering",
    "computer_science", "mathematics", "materials_science",
    "environmental_science", "agriculture", "psychology",
    "economics", "social_science", "law", "interdisciplinary",
}
VALID_DOC_TYPES = {"literature", "patent", "both"}
VALID_SCOPES = {"chinese_first", "international", "global"}
VALID_YEAR_FOCUS = {"recent", "decade", "all"}


class IntentAnalysisAgent:
    """
    自然语言意图解析 Agent。
    从用户自由文本生成结构化项目配置。
    """

    def __init__(self, llm_manager=None):
        self._llm = llm_manager

    async def analyze(
        self,
        user_input: str,
        supplementary_context: str = "",
    ) -> Optional[dict]:
        """
        解析用户自由文本为结构化研究意图。

        Returns:
            解析后的 intent dict，或 None（调用方应回退到手动表单）。
        """
        if not self._llm:
            logger.warning("[IntentAgent] LLM 不可用，需要 fallback 到手动表单")
            return None

        if not user_input or len(user_input.strip()) < 2:
            return None

        system_prompt, user_prompt = build_intent_prompt(
            user_input=user_input,
            supplementary_context=supplementary_context,
        )

        combined = f"{system_prompt}\n\n---\n\n{user_prompt}"

        # 尝试 2 次
        # 启用 JSON mode：让 OpenAI/DeepSeek/Moonshot/Ollama 在 API 层强制返回合法 JSON，
        # 把"三层兜底"的第一层失败率降到接近 0。不支持 JSON mode 的 provider（Anthropic）
        # 会退化为 prompt 提示，_parse_intent 里的 regex 兜底仍然适用。
        for attempt in range(2):
            try:
                result = await self._llm.generate(
                    combined, temperature=0.7,
                    response_format={"type": "json_object"},
                )
                if not result:
                    if attempt == 0:
                        continue
                    return None

                parsed = _parse_intent(result)
                if parsed:
                    logger.info(
                        "[IntentAgent] 解析成功: title='%s', domains=%s, doc_types=%s, confidence=%.2f",
                        parsed.get("title", "")[:30],
                        parsed.get("domains"),
                        parsed.get("doc_types"),
                        parsed.get("confidence", 0),
                    )
                    return parsed

                if attempt == 0:
                    logger.warning("[IntentAgent] 解析失败，重试: %s", result[:150])
                    continue

            except Exception as e:
                logger.warning("[IntentAgent] 解析异常 (attempt %d): %s", attempt + 1, e)
                if attempt == 0:
                    continue

        return None


_PLACEHOLDER_KEYWORDS = (
    "待明确", "不明确", "未明确", "待确认", "未确认",
    "未知意图", "未识别", "未命名", "通用研究",
)
# 调皮可爱小猫人格兜底文案池（LLM 没给 reply 时随机抽一条，避免复读）
_DEFAULT_REPLIES = (
    "喵~这句我没 get 到研究方向，再扔个关键词过来？",
    "呜喵？话有点抽象，给只具体的研究主题来嘛~",
    "(￣▽￣) 猫爪挠了半天没挠出方向，换个说法试试？",
    "喵！想查点什么直说，扔个具体的关键词或研究方向过来~",
    "尾巴抖了抖——没听懂，来个研究领域呗？",
    "嘿嘿，这是闲聊模式没错，但想研究啥直接甩过来更好玩~",
)
# 兜底公式化文案的特征（截图里那种"您好！请告诉我您想研究..."）
_STALE_REPLY_PATTERNS = (
    "您好", "请告诉我您想研究", "请描述您想了解的研究",
    "我将为您", "请随时告诉我",
)


def _reject(reply: Optional[str]) -> dict:
    """构建"非研究请求"短路结果。LLM 给了小猫 reply 就用；否则从兜底池随机抽。"""
    text = (reply or "").strip()
    # 过滤掉 LLM 偷懒复读的公式化客气话
    if not text or any(p in text for p in _STALE_REPLY_PATTERNS):
        text = random.choice(_DEFAULT_REPLIES)
    return {"is_research_request": False, "reply": text[:500]}


def _parse_intent(text: str) -> Optional[dict]:
    """解析 LLM 输出的 intent JSON。"""
    # 优先匹配 is_research_request 的拒绝 JSON，再匹配 title JSON，最后兜底
    match = (
        re.search(r'\{[\s\S]*"is_research_request"[\s\S]*\}', text)
        or re.search(r'\{[\s\S]*"title"[\s\S]*\}', text)
        or re.search(r'\{[\s\S]+\}', text)
    )
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    # ── 非研究请求短路 ──
    if data.get("is_research_request") is False:
        return _reject(data.get("reply"))

    # 校验必需字段
    title = data.get("title")
    if not title or not isinstance(title, str) or len(title) < 2:
        return None

    title = title.strip()

    # 占位符兜底：LLM 有时仍然会编造"研究意图待明确"这类无意义 title
    if any(kw in title for kw in _PLACEHOLDER_KEYWORDS):
        return _reject(data.get("clarification_needed"))

    # 低置信度兜底：confidence < 0.35 也视为非研究请求
    try:
        _conf = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        _conf = 0.5
    if _conf < 0.35:
        return _reject(data.get("clarification_needed"))

    description = data.get("description", title)
    if not isinstance(description, str):
        description = title

    # 校验 domains
    domains = data.get("domains", [])
    if not isinstance(domains, list):
        domains = []
    domains = [d for d in domains if d in VALID_DOMAINS]
    if not domains:
        domains = ["interdisciplinary"]

    # 校验 doc_types
    doc_types = data.get("doc_types", "literature")
    if doc_types not in VALID_DOC_TYPES:
        doc_types = "literature"

    # 校验 scope
    scope = data.get("scope", "international")
    if scope not in VALID_SCOPES:
        scope = "international"

    # 校验 year_focus
    year_focus = data.get("year_focus", "recent")
    if year_focus not in VALID_YEAR_FOCUS:
        year_focus = "recent"

    # key_concepts
    key_concepts = data.get("key_concepts", [])
    if not isinstance(key_concepts, list):
        key_concepts = []
    key_concepts = [str(c) for c in key_concepts[:15]]

    # suggested_sources
    suggested_sources = data.get("suggested_sources", [])
    if not isinstance(suggested_sources, list):
        suggested_sources = ["openalex", "crossref"]
    if not suggested_sources:
        suggested_sources = ["openalex", "crossref"]

    # confidence
    confidence = data.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    # clarification_needed
    clarification = data.get("clarification_needed")
    if clarification and not isinstance(clarification, str):
        clarification = None

    return {
        "is_research_request": True,
        "title": title.strip()[:100],
        "description": description.strip()[:2000],
        "domains": domains,
        "doc_types": doc_types,
        "scope": scope,
        "year_focus": year_focus,
        "key_concepts": key_concepts,
        "suggested_sources": suggested_sources,
        "confidence": confidence,
        "clarification_needed": clarification,
    }
