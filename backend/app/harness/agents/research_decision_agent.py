"""
ResearchDecisionAgent —— 一次 LLM 调用完成"意图解析 + 首轮查询方案"。

替代原先的 IntentAgent + QueryPlanAgent 两次调用。
首轮 prepare_round 会从 project.search_config["precomputed_plan"] 读取
本 Agent 产出的 query_plan，跳过 QueryPlanAgent.agentic_plan 自校验。
2+ 轮仍然走 agentic_plan（保留自校验能力）。

与 IntentAgent 相比：
- 输出的 is_research_request/title/description/domains/... 等字段保持 100% 兼容
  （conversation.py 的 build_intent_envelope 和 _create_project_from_intent 都能直接用）
- 新增一个可选的 query_plan 子字段，解析失败或不存在时优雅降级到"只有 intent"

LLM 不可用 → 返回 None，调用方回退到 IntentAgent 或手动表单。
"""
import json
import logging
import random
import re
from typing import Optional

from app.harness.agents.intent_agent import (
    VALID_DOC_TYPES,
    VALID_DOMAINS,
    VALID_SCOPES,
    VALID_YEAR_FOCUS,
)
from app.services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYWORDS = (
    "待明确", "不明确", "未明确", "待确认", "未确认",
    "未知意图", "未识别", "未命名", "通用研究",
)
# 调皮可爱小猫人格兜底池（LLM 复读公式化客套话时替换）
_DEFAULT_REPLIES = (
    "喵~这句我没 get 到研究方向，再扔个关键词过来？",
    "呜喵？话有点抽象，给只具体的研究主题来嘛~",
    "(￣▽￣) 猫爪挠了半天没挠出方向，换个说法试试？",
    "喵！想查点什么直说，扔个具体的关键词或研究方向过来~",
    "尾巴抖了抖——没听懂，来个研究领域呗？",
    "嘿嘿，想研究啥直接甩过来，猫爪已经磨好啦~",
)
# LLM 偷懒复读训练里的客气模板时，命中这些前缀就强制替换为小猫兜底
_STALE_REPLY_PATTERNS = (
    "您好", "请告诉我您想研究", "请描述您想了解", "请描述您",
    "我将为您", "请随时告诉我", "您可以告诉我",
)


class ResearchDecisionAgent:
    """一次 LLM 调用产出 intent + query_plan。"""

    def __init__(self, llm_manager=None):
        self._llm = llm_manager

    async def decide(
        self,
        user_input: str,
        supplementary_context: str = "",
    ) -> Optional[dict]:
        """
        Returns:
            扁平 dict，含 intent 字段 + 可选 query_plan 子字段；
            非研究请求返回 {is_research_request: False, reply: ...}；
            LLM 不可用或解析失败返回 None。
        """
        if not self._llm:
            logger.warning("[ResearchDecision] LLM 不可用")
            return None
        if not user_input or len(user_input.strip()) < 2:
            return None

        try:
            pf = load_prompt("strategies/research_decision")
        except FileNotFoundError:
            logger.warning("[ResearchDecision] strategies/research_decision.md 缺失")
            return None

        supplement_section = ""
        if supplementary_context:
            supplement_section = f"## 用户补充说明\n{supplementary_context}"

        prompt = pf.render(
            user_input=user_input[:1000],
            supplement_section=supplement_section,
        )

        max_retries = int(pf.get("max_retries", 2) or 2)
        temperature = float(pf.get("temperature", 0.2) or 0.2)

        for attempt in range(max_retries):
            try:
                result = await self._llm.generate(
                    prompt, temperature=temperature,
                    response_format={"type": "json_object"},
                )
                if not result:
                    if attempt + 1 < max_retries:
                        continue
                    return None
                parsed = _parse_decision(result)
                if parsed:
                    qp = parsed.get("query_plan")
                    logger.info(
                        "[ResearchDecision] 解析成功: title=%r domains=%s has_plan=%s base_query=%r",
                        (parsed.get("title") or "")[:30],
                        parsed.get("domains"),
                        qp is not None,
                        ((qp or {}).get("base_query") or "")[:60],
                    )
                    return parsed
                if attempt + 1 < max_retries:
                    logger.warning(
                        "[ResearchDecision] 解析失败，重试: %s", result[:150]
                    )
            except Exception as e:
                logger.warning(
                    "[ResearchDecision] 解析异常 (attempt %d): %s", attempt + 1, e
                )
                if attempt + 1 < max_retries:
                    continue

        return None


def _reject(reply: Optional[str]) -> dict:
    """构建"非研究请求"短路结果。LLM 复读公式化客气话时强制替换为小猫兜底。"""
    text = (reply or "").strip()
    if not text or any(p in text for p in _STALE_REPLY_PATTERNS):
        text = random.choice(_DEFAULT_REPLIES)
    return {"is_research_request": False, "reply": text[:500]}


def _parse_decision(text: str) -> Optional[dict]:
    """解析 LLM 输出的扁平 JSON。"""
    # 去 markdown code fence
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned)

    # 优先尝试 "is_research_request" 的完整对象，再兜底
    match = (
        re.search(r'\{[\s\S]*"is_research_request"[\s\S]*\}', cleaned)
        or re.search(r'\{[\s\S]*"title"[\s\S]*\}', cleaned)
        or re.search(r'\{[\s\S]+\}', cleaned)
    )
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    # 非研究请求短路
    if data.get("is_research_request") is False:
        return _reject(data.get("reply"))

    # —— 意图字段校验（和 IntentAnalysisAgent._parse_intent 保持一致）——
    title = data.get("title")
    if not title or not isinstance(title, str) or len(title) < 2:
        return None
    title = title.strip()

    if any(kw in title for kw in _PLACEHOLDER_KEYWORDS):
        return _reject(data.get("clarification_needed"))

    try:
        _conf = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        _conf = 0.5
    if _conf < 0.35:
        return _reject(data.get("clarification_needed"))

    description = data.get("description", title)
    if not isinstance(description, str):
        description = title

    domains = data.get("domains", [])
    if not isinstance(domains, list):
        domains = []
    domains = [d for d in domains if d in VALID_DOMAINS]
    if not domains:
        domains = ["interdisciplinary"]

    doc_types = data.get("doc_types", "literature")
    if doc_types not in VALID_DOC_TYPES:
        doc_types = "literature"

    scope = data.get("scope", "international")
    if scope not in VALID_SCOPES:
        scope = "international"

    year_focus = data.get("year_focus", "recent")
    if year_focus not in VALID_YEAR_FOCUS:
        year_focus = "recent"

    key_concepts = data.get("key_concepts", [])
    if not isinstance(key_concepts, list):
        key_concepts = []
    key_concepts = [str(c) for c in key_concepts[:15]]

    suggested_sources = data.get("suggested_sources", [])
    if not isinstance(suggested_sources, list):
        suggested_sources = ["openalex", "crossref"]
    if not suggested_sources:
        suggested_sources = ["openalex", "crossref"]

    clarification = data.get("clarification_needed")
    if clarification and not isinstance(clarification, str):
        clarification = None

    # —— query_plan 子字段（可选，失败则返回 None 表示降级到只有 intent）——
    query_plan = _parse_query_plan(data.get("query_plan"))

    return {
        "is_research_request": True,
        "title": title[:100],
        "description": description.strip()[:2000],
        "domains": domains,
        "doc_types": doc_types,
        "scope": scope,
        "year_focus": year_focus,
        "key_concepts": key_concepts,
        "suggested_sources": suggested_sources,
        "confidence": max(0.0, min(1.0, _conf)),
        "clarification_needed": clarification,
        "query_plan": query_plan,
    }


def _parse_query_plan(raw) -> Optional[dict]:
    """解析可选的 query_plan 子字段；结构不对 → 返回 None（优雅降级）。"""
    if not isinstance(raw, dict):
        return None

    base_query = raw.get("base_query")
    if not isinstance(base_query, str) or len(base_query.strip()) < 3:
        return None
    base_query = base_query.strip()

    chinese_query = raw.get("chinese_query")
    if chinese_query is not None and not isinstance(chinese_query, str):
        chinese_query = None
    if isinstance(chinese_query, str):
        chinese_query = chinese_query.strip() or None

    from datetime import datetime
    current_year = datetime.now().year

    # LLM 时间幻觉修正：LLM 经常按训练数据的 cutoff 年份算"近 N 年"
    # 例如 LLM 以为现在是 2024 → 给 year_to=2024 year_from=2019
    # 策略：保留 LLM 的"跨度"语义，但把 year_to 对齐到 current_year
    orig_year_to = raw.get("year_to")
    orig_year_from = raw.get("year_from")

    def _valid_year(y) -> bool:
        return isinstance(y, int) and 1900 <= y <= current_year + 1

    if _valid_year(orig_year_to) and abs(orig_year_to - current_year) <= 1:
        # LLM 给的 year_to 已经是当前年附近，信任它
        year_to = orig_year_to
        if _valid_year(orig_year_from) and orig_year_from < year_to:
            year_from = orig_year_from if year_to - orig_year_from <= 20 else year_to - 9
        else:
            year_from = None
    else:
        # LLM year_to 存在时间幻觉 → 强制对齐到 current_year，同时按原 span 调整 year_from
        year_to = current_year
        if _valid_year(orig_year_to) and _valid_year(orig_year_from) and orig_year_from < orig_year_to:
            span = orig_year_to - orig_year_from
            if 0 < span <= 20:
                year_from = year_to - span  # 保留 LLM 的时间跨度语义
            else:
                year_from = year_to - 9
        else:
            year_from = None

    language_scope = raw.get("language_scope", "international")
    if language_scope not in ("chinese_first", "international", "global"):
        language_scope = "international"

    rationale = raw.get("rationale") or ""
    if not isinstance(rationale, str):
        rationale = ""

    return {
        "base_query": base_query,
        "chinese_query": chinese_query,
        "year_from": year_from,
        "year_to": year_to,
        "language_scope": language_scope,
        "rationale": rationale[:300],
    }
