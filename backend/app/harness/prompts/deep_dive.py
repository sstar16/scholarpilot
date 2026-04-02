"""
Deep Dive Agent prompt template.
对单篇文献进行全文深度分析。
"""

DEEP_DIVE_PROMPT = """你是一位资深科研文献分析专家。请深入分析以下文献，结合用户的研究目标给出详细评价。

## 用户研究目标
{project_description}

{memory_section}

## 文献信息

- **标题**: {title}
- **作者**: {authors}
- **来源**: {source}
- **发表日期**: {publication_date}
- **DOI**: {doi}

## 文献内容

{content}

## 任务

请对这篇文献进行深度分析，输出以下 JSON（不要包含其他文字）：
```json
{{
  "detailed_analysis": "300-500字的深度分析，包括研究背景、核心发现、创新点",
  "methodology": "研究方法评述（100字以内）",
  "key_findings": ["核心发现1", "核心发现2", "..."],
  "limitations": ["局限性1", "..."],
  "relevance_to_project": "与用户研究目标的具体关联分析（100字以内）",
  "updated_one_liner": "更新后的一句话总结（30字以内）",
  "recommended_followup": ["建议后续关注的相关方向1", "..."]
}}
```"""


def build_deep_dive_prompt(
    project_description: str,
    doc: dict,
    content: str,
    user_memory: str = "",
) -> str:
    memory_section = ""
    if user_memory:
        memory_section = f"## 用户研究偏好\n{user_memory[:500]}"

    return DEEP_DIVE_PROMPT.format(
        project_description=project_description[:500],
        memory_section=memory_section,
        title=doc.get("title", "未知"),
        authors=(doc.get("authors") or "未知")[:200],
        source=doc.get("source", "未知"),
        publication_date=doc.get("publication_date", "未知"),
        doi=doc.get("doi") or "无",
        content=content[:8000],
    )
