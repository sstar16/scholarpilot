"""
QueryPlan Agent prompt (legacy single-shot) —— 从 md 模板构建。
模板: backend/app/prompts/agents/query_plan_legacy.md

Agentic 模式用的是 prompts/agents/query_plan_agentic.md（在 query_plan_agent.py 里加载）。
"""
from app.services.prompt_loader import load_prompt


def build_query_plan_prompt(
    project_description: str,
    memory_text: str,
    round_number: int,
    max_rounds: int,
    tool_reliability: dict,
    disabled_sources: set,
    prev_source_stats: dict = None,
) -> tuple[str, str]:
    """
    构建 QueryPlanAgent.plan() prompt（legacy 路径，agentic 失败时回退）。

    Returns:
        (combined_prompt, "") — 兼容原 (system, user) 元组签名。
    """
    memory_section = memory_text[:800] if memory_text else "（首轮，无历史记忆）"

    # 格式化工具可靠性（只展示未被禁用的源）
    reliability_lines = []
    for tool_id, rel in sorted(tool_reliability.items()):
        if tool_id not in disabled_sources:
            if isinstance(rel, (int, float)):
                rel_val = rel
            elif isinstance(rel, dict):
                rel_val = rel.get("reliability", 1.0)
            else:
                rel_val = 1.0
            reliability_lines.append(f"{tool_id}({rel_val:.0%})")
    reliability_str = ", ".join(reliability_lines) if reliability_lines else "无数据"

    disabled_str = ", ".join(sorted(disabled_sources)) if disabled_sources else "无"

    prev_stats_section = ""
    if prev_source_stats and round_number > 1:
        stats_lines = []
        for src, stat in prev_source_stats.items():
            count = stat.get("count", 0) if isinstance(stat, dict) else 0
            stats_lines.append(f"{src}: {count}篇")
        prev_stats_section = f"- 上轮各源返回：{', '.join(stats_lines)}"

    pf = load_prompt("agents/query_plan_legacy")
    rendered = pf.render(
        project_description=project_description[:600],
        memory_section=memory_section,
        round_number=round_number,
        max_rounds=max_rounds,
        tool_reliability=reliability_str,
        disabled_sources=disabled_str,
        prev_stats_section=prev_stats_section,
    )
    return rendered, ""
