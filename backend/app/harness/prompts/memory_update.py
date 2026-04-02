"""
Memory Update Agent prompt template.
根据用户反馈的 4-bucket 文档，更新用户研究偏好的结构化记忆。
"""

MEMORY_UPDATE_PROMPT = """你是一位科研助手，负责维护用户的研究偏好记忆。根据用户对文献的反馈，更新记忆文档。

## 项目描述
{project_description}

## 当前记忆（第 {memory_version} 版）
{current_memory}

## 本轮用户反馈

### 非常相关的文献（用户评分 = 2）
{very_relevant_docs}

### 相关的文献（用户评分 = 1）
{relevant_docs}

### 不确定的文献（用户评分 = 0）
{uncertain_docs}

### 无关的文献（用户评分 = -1）
{irrelevant_docs}

## 任务

根据以上反馈，更新用户研究偏好记忆。请：
1. 从"非常相关"和"相关"文献中提炼用户真正关心的主题、方法、材料
2. 从"无关"文献中识别用户想排除的方向
3. 保留前版记忆中仍然有效的内容，移除被新反馈否定的内容
4. 如果某个关键词/主题在"非常相关"和"无关"中都出现，以用户最新反馈为准

严格按以下 JSON 格式输出（不要包含其他文字）：
```json
{{
  "research_focus": "用户核心研究方向的一句话描述",
  "preferred_topics": ["主题1", "主题2", "..."],
  "excluded_topics": ["排除主题1", "..."],
  "methodology_preferences": ["偏好方法1", "..."],
  "key_authors": ["重要作者1", "..."],
  "source_preferences": ["偏好来源1", "..."],
  "notes": "其他观察（如用户关注特定年份范围、特定国家的研究等）"
}}
```"""


def build_memory_update_prompt(
    project_description: str,
    current_memory: str,
    memory_version: int,
    feedback_buckets: dict,
) -> str:
    """
    构建记忆更新 prompt。
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

    return MEMORY_UPDATE_PROMPT.format(
        project_description=project_description[:500],
        current_memory=current_memory or "（首次，无历史记忆）",
        memory_version=memory_version,
        very_relevant_docs=format_bucket(feedback_buckets.get(2, [])),
        relevant_docs=format_bucket(feedback_buckets.get(1, [])),
        uncertain_docs=format_bucket(feedback_buckets.get(0, [])),
        irrelevant_docs=format_bucket(feedback_buckets.get(-1, [])),
    )
