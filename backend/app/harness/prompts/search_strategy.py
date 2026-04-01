"""
Search Strategy Agent prompt template.
Designed for minimal token usage (~400 input, ~150 output).
"""

SEARCH_STRATEGY_PROMPT = """You are a research search strategy planner. Given the context below, produce a JSON search plan.

CONTEXT:
- Topic: {topic}
- Round: {round_number} of {max_rounds}
- Profile keywords (positive): {profile_positive}
- Profile keywords (negative): {profile_negative}
- Available tools with reliability: {tool_stats}
- Previous round stats: {prev_stats}

RULES:
1. ALWAYS select at least 6 tools. Must include: openalex, europe_pmc, crossref, arxiv. Add more based on topic.
2. For round 1-2: 5-10 year range, 20 results per source
3. For round 3+: wider time range (20+ years or all), 30+ results, use profile keywords as boost terms
4. Only exclude tools with reliability < 0.2
5. Chinese-language tools (openalex_zh, soopat) should be included when topic contains Chinese
6. Patent tools (epo_ops, lens_patent) should be included for applied/industrial topics
7. More tools = better coverage. When in doubt, include more sources.

OUTPUT (JSON only, no explanation):
{{
  "tools": [
    {{"tool_id": "openalex", "max_results": 20, "priority": 1}},
    ...
  ],
  "year_range": {{"from": 2021, "to": 2026}},
  "boost_terms": ["term1", "term2"],
  "exclude_terms": ["term1"],
  "scoring_adjustments": {{
    "keyword_weight": 0.6,
    "citation_weight": 0.25,
    "recency_weight": 0.15
  }},
  "rationale": "Brief explanation of strategy"
}}"""


def build_strategy_prompt(
    topic: str,
    round_number: int,
    max_rounds: int,
    profile_positive: list,
    profile_negative: list,
    tool_stats: dict,
    prev_stats: dict,
) -> str:
    """Build the strategy prompt with context injected."""
    return SEARCH_STRATEGY_PROMPT.format(
        topic=topic[:200],
        round_number=round_number,
        max_rounds=max_rounds,
        profile_positive=", ".join(profile_positive[:10]) or "none",
        profile_negative=", ".join(profile_negative[:5]) or "none",
        tool_stats=_format_tool_stats(tool_stats),
        prev_stats=_format_prev_stats(prev_stats),
    )


def _format_tool_stats(stats: dict) -> str:
    """Compact format: tool_id(reliability) e.g. openalex(0.95)"""
    if not stats:
        return "no stats yet"
    parts = [f"{tid}({rel:.1f})" for tid, rel in sorted(stats.items(), key=lambda x: -x[1])]
    return ", ".join(parts[:15])


def _format_prev_stats(stats: dict) -> str:
    """Compact format from previous round source_stats."""
    if not stats:
        return "first round"
    parts = []
    for src, info in stats.items():
        if isinstance(info, dict):
            parts.append(f"{src}:{info.get('count', 0)}docs/{info.get('execution_ms', 0)}ms")
    return ", ".join(parts[:10]) or "no data"
