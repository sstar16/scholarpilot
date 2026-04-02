"""
QueryPlan Agent — Agent-First 查询规划。
直接从 project.description + memory_text 生成完整 QueryPlan。
替代 build_query() + AgentSearchPlan overlay 的双层架构。

LLM 不可用时 returns None → 调用方回退到 build_query() fallback。
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional, Set

from app.harness.prompts.query_plan import build_query_plan_prompt

logger = logging.getLogger(__name__)


class QueryPlanAgent:
    """
    Agent-First query planning.
    Generates a complete QueryPlan from project description + memory.
    """

    def __init__(self, llm_manager=None):
        self._llm = llm_manager

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
        生成完整 QueryPlan。

        Returns:
            QueryPlan instance, or None on failure (caller should fallback).
        """
        if not self._llm:
            logger.warning("[QueryPlanAgent] LLM 不可用，需要 fallback")
            return None

        if disabled_sources is None:
            disabled_sources = {
                s.strip()
                for s in os.getenv("DISABLED_SOURCES", "").split(",")
                if s.strip()
            }

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

        # 尝试 2 次
        for attempt in range(2):
            try:
                result = await self._llm.generate(combined, temperature=0.2)
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
                    # 附加 rationale（不在 dataclass 中，用动态属性）
                    qp._rationale = parsed.get("rationale", "")

                    logger.info(
                        "[QueryPlanAgent] 规划成功: query='%s', %d sources, %s, rationale='%s'",
                        qp.base_query[:50],
                        len(qp.sources),
                        f"{qp.year_from}-{qp.year_to}",
                        parsed.get("rationale", "")[:80],
                    )
                    return qp

                if attempt == 0:
                    logger.warning("[QueryPlanAgent] 解析失败，重试: %s", result[:150])
                    continue

            except Exception as e:
                logger.warning("[QueryPlanAgent] 规划异常 (attempt %d): %s", attempt + 1, e)
                if attempt == 0:
                    continue

        return None


def _parse_query_plan(text: str, disabled_sources: Set[str]) -> Optional[Dict]:
    """解析 LLM 输出的 QueryPlan JSON。"""
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

    # 过滤被禁用的源
    sources = data.get("sources", [])
    if not isinstance(sources, list) or len(sources) < 1:
        sources = ["openalex", "crossref", "arxiv"]
    sources = [s for s in sources if s not in disabled_sources]
    if not sources:
        sources = ["openalex"]

    # expanded_terms
    expanded = data.get("expanded_terms", [])
    if not isinstance(expanded, list):
        expanded = []
    # 确保 base_query 的词也在 expanded_terms 中（传统评分引擎需要）
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
