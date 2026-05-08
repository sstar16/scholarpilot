"""
Scoring Agent prompt —— 从 md 模板构建。
模板: backend/app/prompts/agents/scoring.md
"""
from app.services.prompt_loader import load_prompt


def build_scoring_prompt(
    project_description: str,
    doc: dict,
    user_memory: str = "",
    bucket_examples: str = "",
) -> tuple[str, str]:
    """
    构建单篇文献评分 prompt。

    Returns:
        (combined_prompt, "") — 兼容原 (system, user) 元组签名。
    """
    memory_section = ""
    if user_memory:
        memory_section = f"## 用户研究偏好记忆\n{user_memory[:800]}"
    if bucket_examples:
        memory_section += f"\n\n## 用户已分类的高相关文献（参考）\n{bucket_examples[:600]}"

    extra_parts = []
    if doc.get("ai_key_points"):
        points = doc["ai_key_points"]
        if isinstance(points, list):
            points = "; ".join(str(p) for p in points[:5])
        extra_parts.append(f"- **AI 提取关键点**: {points}")
    if doc.get("journal"):
        extra_parts.append(f"- **期刊/会议**: {doc['journal']}")
    if doc.get("doi"):
        extra_parts.append(f"- **DOI**: {doc['doi']}")
    extra_info = "\n".join(extra_parts) if extra_parts else ""

    pf = load_prompt("agents/scoring")
    rendered = pf.render(
        project_description=project_description,
        memory_section=memory_section,
        title=doc.get("title", "未知"),
        doc_type=doc.get("doc_type", "paper"),
        source=doc.get("source", "未知"),
        publication_date=doc.get("publication_date", "未知"),
        citation_count=doc.get("citation_count", 0),
        authors=(doc.get("authors") or "未知")[:200],
        abstract=doc.get("abstract") or doc.get("ai_summary") or "无摘要",
        extra_info=extra_info,
    )
    return rendered, ""
