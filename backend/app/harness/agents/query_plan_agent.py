"""
QueryPlan Agent — Agent-First 查询规划。

两种模式：
- plan()          : 单次 LLM 调用，快但不自校验（legacy, fallback）
- agentic_plan() : Tool-using loop，用 search_preview 试查自校验（推荐）

LLM 不可用时 returns None → 调用方回退到 build_query() fallback。
"""
import json
import logging
import re
from typing import Dict, List, Optional, Set

from app.harness.prompts.query_plan import build_query_plan_prompt
from app.services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


# ──────────────────────── Tools for Agentic Loop ────────────────────────

async def _tool_search_preview(query: str, source: str = "local_kb") -> dict:
    """
    Agentic tool: 试查一个查询，返回命中数 + 前 5 个标题。
    Agent 用这个观察自己的查询效果，决定是否调整或 finalize。
    """
    if not query or not query.strip():
        return {"error": "empty query"}
    try:
        from app.services.fetchers.international import ALL_FETCHERS
        fetcher = ALL_FETCHERS.get(source)
        if not fetcher:
            return {"error": f"source '{source}' unavailable"}
        results = await fetcher.fetch(query=query.strip(), max_results=5)
        return {
            "count": len(results),
            "top_titles": [
                (r.get("title") or "")[:100] for r in results[:5]
            ],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ──────────────────────── Agentic Loop System Prompt ────────────────────────
# System prompt + 参数（max_iterations / preview_source）都在
# backend/app/prompts/agents/query_plan_agentic.md 里维护。
# 改 md 后无需重启 worker —— mtime 热重载。


class QueryPlanAgent:
    """Agent-First query planning, supports both single-shot and tool-using modes."""

    def __init__(self, llm_manager=None):
        self._llm = llm_manager

    # ═══════════════════════════════════════════════════════════════════
    # Agentic Mode (tool-using, self-verifying)
    # ═══════════════════════════════════════════════════════════════════

    async def agentic_plan(
        self,
        project_description: str,
        memory_text: str = "",
        max_iterations: Optional[int] = None,
    ):
        """
        Tool-using agent loop:
        LLM 用 search_preview 自己试查、观察命中、调整、finalize。

        模型变强时 agent 自动变强，不依赖硬规则。

        System prompt + max_iterations 从 prompts/agents/query_plan_agentic.md 读取（mtime 热重载）。

        Returns:
            QueryPlan with optional _rationale / _clarification_needed / _clarification_message
            None if LLM unavailable or loop exceeds budget
        """
        if not self._llm:
            logger.warning("[AgenticPlan] LLM 不可用")
            return None

        prompt_file = load_prompt("agents/query_plan_agentic")
        if max_iterations is None:
            max_iterations = int(prompt_file.get("max_iterations", 5) or 5)

        history = [
            {
                "role": "user",
                "content": (
                    f"【研究描述】\n{project_description}\n\n"
                    + (f"【历史记忆】\n{memory_text}\n\n" if memory_text else "")
                    + "请开始规划。先 search_preview 试你判断的核心概念。"
                ),
            }
        ]

        for iteration in range(max_iterations):
            prompt = self._render_conversation(history, system_prompt=prompt_file.body)
            response = await self._llm.generate(
                prompt, temperature=0.1,
                response_format={"type": "json_object"},
            )

            if not response:
                logger.warning("[AgenticPlan] iter=%d LLM 返回空", iteration)
                return None

            action = _parse_action_json(response)
            if not action:
                logger.warning(
                    "[AgenticPlan] iter=%d 解析失败: %s", iteration, response[:200]
                )
                history.append({"role": "assistant", "content": response[:500]})
                history.append({
                    "role": "user",
                    "content": "你的回复不是合法 JSON。请严格输出一个 JSON 对象，无任何其它文字。",
                })
                continue

            history.append({
                "role": "assistant",
                "content": json.dumps(action, ensure_ascii=False),
            })

            act_name = action.get("action")

            if act_name == "search_preview":
                query = action.get("query", "")
                source = action.get("source", "local_kb")
                result = await _tool_search_preview(query, source)
                logger.info(
                    "[AgenticPlan] iter=%d preview(%r) → count=%s",
                    iteration, query[:50], result.get("count"),
                )
                history.append({
                    "role": "user",
                    "content": f"[tool_result]\n{json.dumps(result, ensure_ascii=False)}",
                })
                continue

            if act_name == "finalize":
                plan_data = action.get("plan") or {}
                logger.info(
                    "[AgenticPlan] iter=%d FINALIZE: base_query=%r clarification=%s",
                    iteration,
                    (plan_data.get("base_query") or "")[:60],
                    plan_data.get("clarification_needed"),
                )
                return self._build_query_plan(plan_data)

            # Unknown action
            history.append({
                "role": "user",
                "content": "未知 action。只能用 search_preview 或 finalize。",
            })

        logger.warning("[AgenticPlan] 超出预算 %d 次仍未 finalize", max_iterations)
        return None

    def _render_conversation(self, history: List[Dict], system_prompt: str) -> str:
        """把对话历史渲染成一个大 prompt（用于不支持 native messages 的 provider）。"""
        parts = [system_prompt, ""]
        for msg in history:
            role = msg["role"].upper()
            parts.append(f"=== {role} ===")
            parts.append(msg["content"])
            parts.append("")
        parts.append("=== ASSISTANT ===")
        return "\n".join(parts)

    def _build_query_plan(self, plan_data: dict):
        """把 agent finalize 的 dict 转成 QueryPlan dataclass。"""
        from app.services.query_builder import QueryPlan
        from datetime import datetime

        base_query = (plan_data.get("base_query") or "").strip()

        # clarification path: build minimal plan to surface the message
        clarification_needed = bool(plan_data.get("clarification_needed"))
        clarification_message = plan_data.get("clarification_message") or ""

        if not base_query and not clarification_needed:
            return None

        current_year = datetime.now().year
        year_to = plan_data.get("year_to")
        if not isinstance(year_to, int) or year_to > current_year + 1:
            year_to = current_year
        year_from = plan_data.get("year_from")
        if year_from is not None and (not isinstance(year_from, int) or year_from < 1900):
            year_from = None

        language_scope = plan_data.get("language_scope", "international")
        if language_scope not in ("chinese_first", "international", "global"):
            language_scope = "international"

        qp = QueryPlan(
            base_query=base_query or "placeholder",
            expanded_terms=[w for w in base_query.split() if len(w) >= 2],
            exclude_terms=plan_data.get("exclude_terms", []) or [],
            year_from=year_from,
            year_to=year_to,
            sources=["local_kb"],  # search_mode filter will override later
            max_results_per_source=plan_data.get("max_per_source", 20),
            language_scope=language_scope,
            original_chinese_query=plan_data.get("chinese_query"),
        )
        qp._rationale = (plan_data.get("rationale") or "")[:300]
        qp._clarification_needed = clarification_needed
        qp._clarification_message = clarification_message[:500]
        return qp

    # ═══════════════════════════════════════════════════════════════════
    # Legacy Single-shot Mode (fallback)
    # ═══════════════════════════════════════════════════════════════════

    async def plan(
        self,
        project_description: str,
        memory_text: str = "",
        round_number: int = 1,
        max_rounds: int = 5,
        tool_reliability: Dict = None,
        prev_source_stats: Dict = None,
        disabled_sources: Set[str] = None,
    ):
        """
        Legacy single-shot plan. Kept as fallback when agentic_plan fails.
        """
        if not self._llm:
            logger.warning("[QueryPlanAgent] LLM 不可用，需要 fallback")
            return None

        if disabled_sources is None:
            from app.services.source_config_store import get_effective_disabled
            disabled_sources = await get_effective_disabled()

        system_prompt, user_prompt = build_query_plan_prompt(
            project_description=project_description,
            memory_text=memory_text,
            round_number=round_number,
            max_rounds=max_rounds,
            tool_reliability=tool_reliability or {},
            disabled_sources=disabled_sources,
            prev_source_stats=prev_source_stats,
        )

        combined = f"{system_prompt}\n\n---\n\n{user_prompt}"

        for attempt in range(2):
            try:
                result = await self._llm.generate(
                    combined, temperature=0.2,
                    response_format={"type": "json_object"},
                )
                if not result:
                    if attempt == 0:
                        continue
                    return None

                parsed = _parse_query_plan(result, disabled_sources)
                if parsed:
                    from app.services.query_builder import QueryPlan

                    qp = QueryPlan(
                        base_query=parsed["base_query"],
                        expanded_terms=parsed["expanded_terms"],
                        exclude_terms=parsed["exclude_terms"],
                        year_from=parsed["year_from"],
                        year_to=parsed["year_to"],
                        sources=parsed["sources"],
                        max_results_per_source=parsed["max_per_source"],
                        language_scope=parsed["language_scope"],
                        original_chinese_query=parsed.get("chinese_query"),
                    )
                    qp._rationale = parsed.get("rationale", "")

                    logger.info(
                        "[QueryPlanAgent.plan] 规划成功: query='%s', %d sources, %s",
                        qp.base_query[:50],
                        len(qp.sources),
                        f"{qp.year_from}-{qp.year_to}",
                    )
                    return qp

                if attempt == 0:
                    logger.warning("[QueryPlanAgent.plan] 解析失败，重试: %s", result[:150])
                    continue

            except Exception as e:
                logger.warning("[QueryPlanAgent.plan] 规划异常 (attempt %d): %s", attempt + 1, e)
                if attempt == 0:
                    continue

        return None


# ──────────────────────── JSON Parsing Helpers ────────────────────────

def _parse_action_json(text: str) -> Optional[dict]:
    """Extract a valid JSON 'action' object from agent response.

    Tolerates:
    - Markdown code fences (```json ... ```)
    - Leading/trailing explanations
    - Nested braces (uses balanced brace scanning, not greedy regex)
    - Multiple candidate objects (picks the first one with 'action' key)
    """
    if not text:
        return None
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?\s*```\s*$", "", text)

    # Scan for balanced JSON objects
    candidates = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : i + 1])
                start = -1

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "action" in obj:
            return obj

    # Fallback: last resort greedy match (might parse partial)
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return None


def _parse_query_plan(text: str, disabled_sources: Set[str]) -> Optional[Dict]:
    """解析 legacy plan() 的 LLM JSON 输出。"""
    match = re.search(r'\{[\s\S]*"base_query"[\s\S]*\}', text)
    if not match:
        match = re.search(r'\{[\s\S]+\}', text)
        if not match:
            return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    base_query = data.get("base_query")
    if not base_query or not isinstance(base_query, str) or len(base_query) < 3:
        return None

    sources = data.get("sources", [])
    if not isinstance(sources, list) or len(sources) < 1:
        sources = ["openalex", "crossref", "arxiv"]
    sources = [s for s in sources if s not in disabled_sources]
    if not sources:
        sources = ["openalex"]

    expanded = data.get("expanded_terms", [])
    if not isinstance(expanded, list):
        expanded = []
    base_words = [w for w in base_query.split() if len(w) >= 2]
    for w in base_words:
        if w.lower() not in [e.lower() for e in expanded]:
            expanded.insert(0, w)

    from datetime import datetime
    current_year = datetime.now().year

    year_to = data.get("year_to", current_year)
    if not isinstance(year_to, int) or year_to > current_year + 1:
        year_to = current_year

    year_from = data.get("year_from")
    if year_from is not None:
        if not isinstance(year_from, int) or year_from < 1900:
            year_from = None

    max_per_source = data.get("max_per_source", 20)
    if not isinstance(max_per_source, int) or max_per_source < 5:
        max_per_source = 20

    language_scope = data.get("language_scope", "international")
    if language_scope not in ("chinese_first", "international", "global"):
        language_scope = "international"

    return {
        "base_query": base_query.strip(),
        "chinese_query": data.get("chinese_query"),
        "expanded_terms": expanded,
        "exclude_terms": data.get("exclude_terms", []) or [],
        "year_from": year_from,
        "year_to": year_to,
        "sources": sources,
        "max_per_source": max_per_source,
        "language_scope": language_scope,
        "rationale": str(data.get("rationale", ""))[:200],
    }
