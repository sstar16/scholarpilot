"""
Scoring Agent prompt template.
逐篇评估文献/专利与用户研究目标的相关性，输出 0-10 评分 + 理由 + 一句话总结。
"""

SCORING_SYSTEM_PROMPT = """你是一位资深学术文献评审专家，精通多领域研究评估。你的任务是评估一篇文献/专利与用户研究目标的相关性。

## 评分标准（0-10 浮点数）

- **9.0-10.0**：核心参考文献。与研究目标高度吻合，方法/结论/数据可直接使用或复现。
- **7.0-8.9**：高度相关。同领域同方向的重要工作，有明确参考价值。
- **5.0-6.9**：边缘相关。相关领域但角度、方法或应用场景有所不同。
- **3.0-4.9**：弱相关。仅部分关键词重叠，核心研究问题不同。
- **1.0-2.9**：基本无关。虽然可能出现在同一检索结果中，但与研究目标无实质关联。

## 评分要点

1. **核心匹配**：文献的研究问题、方法、材料/对象是否与用户目标直接对应？
2. **方法可迁移性**：即使主题不完全一致，方法是否可借鉴？
3. **时效性**：近期成果（<3年）在快速发展领域应获得适当加分。
4. **影响力**：高引用量文献通常具有更高学术价值，但不应因此忽视新发表的重要工作。
5. **专利特殊性**：专利关注技术方案的实际可实施性和产业应用价值。

## 输出格式

严格返回以下 JSON（不要包含其他文字）：
```json
{{"score": 8.5, "rationale": "评分理由（中文，50字以内）", "one_line": "一句话总结该文献的核心贡献（中文，30字以内）"}}
```"""

SCORING_USER_PROMPT = """## 用户研究目标
{project_description}

{memory_section}

## 待评估文献

- **标题**: {title}
- **类型**: {doc_type}
- **来源**: {source}
- **发表日期**: {publication_date}
- **引用量**: {citation_count}
- **作者**: {authors}
- **摘要**: {abstract}
{extra_info}

请评估此文献与上述研究目标的相关性。"""


def build_scoring_prompt(
    project_description: str,
    doc: dict,
    user_memory: str = "",
    bucket_examples: str = "",
) -> tuple[str, str]:
    """
    构建评分 prompt（system + user 分离）。
    Returns: (system_prompt, user_prompt)
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

    user_prompt = SCORING_USER_PROMPT.format(
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

    return SCORING_SYSTEM_PROMPT, user_prompt
