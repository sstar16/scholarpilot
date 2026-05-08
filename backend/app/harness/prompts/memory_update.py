"""
Memory Update Agent prompt —— 从 md 模板构建。
模板: backend/app/prompts/agents/memory_update.md
"""
from app.services.prompt_loader import load_prompt


def build_memory_update_prompt(
    project_description: str,
    current_memory: str,
    memory_version: int,
    feedback_buckets: dict,
) -> str:
    """
    构建记忆更新 prompt（返回单 string，与原签名一致）。

    feedback_buckets: {2: [...], 1: [...], 0: [...], -1: [...]}
    每个 entry: {"title": ..., "one_line_summary": ..., "source": ...}
    """
    def format_bucket(entries: list) -> str:
        if not entries:
            return "（无）"
        lines = []
        for e in entries[:10]:  # 最多 10 篇
            title = e.get("title", "未知")[:100]
            summary = e.get("one_line_summary", "")
            source = e.get("source", "")
            line = f"- [{source}] {title}"
            if summary:
                line += f" — {summary}"
            lines.append(line)
        return "\n".join(lines)

    pf = load_prompt("agents/memory_update")
    return pf.render(
        project_description=project_description[:500],
        current_memory=current_memory or "（首次，无历史记忆）",
        memory_version=memory_version,
        very_relevant_docs=format_bucket(feedback_buckets.get(2, [])),
        relevant_docs=format_bucket(feedback_buckets.get(1, [])),
        uncertain_docs=format_bucket(feedback_buckets.get(0, [])),
        irrelevant_docs=format_bucket(feedback_buckets.get(-1, [])),
    )
