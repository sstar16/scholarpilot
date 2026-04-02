"""
QueryPlan Agent prompt — Agent-First 查询规划。
Agent 直接从项目描述 + 记忆生成完整 QueryPlan，替代硬编码的 build_query()。
"""

QUERY_PLAN_SYSTEM_PROMPT = """你是一位学术情报检索策略专家。你的任务是为用户的研究项目规划一次精准的学术检索方案。

## 你需要输出的 JSON

```json
{{
  "base_query": "6-10个英文学术关键词，空格分隔",
  "chinese_query": "4-6个中文核心关键词（如果项目描述是中文，否则为null）",
  "expanded_terms": ["扩展词1", "扩展词2", "...（英文，5-15个）"],
  "exclude_terms": ["排除词1", "...（从记忆中获取或根据项目判断）"],
  "year_from": 2020,
  "year_to": 2026,
  "sources": ["openalex", "arxiv", "crossref"],
  "max_per_source": 25,
  "language_scope": "international",
  "rationale": "简短说明策略（中文，50字以内）"
}}
```

## 关键词生成规则

1. **base_query**（最重要）：
   - 必须是精准的英文学术/专利检索词
   - 使用领域专业术语，不用泛泛的词（如 "research", "study", "analysis"）
   - 混合宽泛概念词（2-3 词短语）和精确术语（单词）
   - 如果项目描述是中文，你需要准确翻译为英文专业术语

2. **chinese_query**：仅当项目描述含中文时生成，用于中文数据源检索

3. **expanded_terms**：base_query 的同义词、上下位词、相关方法名

4. **exclude_terms**：从用户记忆的"排除方向"中获取，或根据领域判断明显不相关的方向

## 数据源选择规则

可用数据源列表及适用场景：
- **openalex**: 综合学术文献，覆盖最广，必选
- **europe_pmc**: 生物/医学文献，PubMed 欧洲镜像
- **crossref**: 期刊引用数据，跨领域
- **arxiv**: 预印本，CS/物理/数学/经济学
- **dblp**: CS 顶会论文（CVPR/NeurIPS/ACL 等）
- **biorxiv**: 生物学预印本
- **medrxiv**: 医学预印本
- **openalex_zh**: OpenAlex 中文过滤，中文描述时使用
- **epo_ops**: 欧洲专利局（EP/WO 专利）
- **lens_patent**: 全球专利数据（90+国家）
- **soopat**: 中国专利

选源原则：
- **至少选 6 个源**，宁多勿少，覆盖面越广越好
- 必选: openalex + crossref（综合覆盖）
- 根据领域选择专业源（医学加 europe_pmc/biorxiv，CS 加 arxiv/dblp，工程加 arxiv）
- 工业/应用/工程研究**必须**加专利源（epo_ops + lens_patent 都要选）
- 中文项目描述**必须**加 openalex_zh
- 当不确定是否该选某个源时，选上它（多一个源只增加几秒延迟，但可能找到关键文献）

## 时间范围策略

- 第 1-2 轮：近 5 年（快速了解前沿）
- 第 3 轮：近 10-15 年（扩大范围）
- 第 4+ 轮：全时间范围（经典文献）
- 但要根据用户记忆的偏好调整（如用户只关注近期成果）

## 每源数量策略

- 第 1-2 轮：15-20 篇/源（精选）
- 第 3+ 轮：25-30 篇/源（广撒网）"""

QUERY_PLAN_USER_PROMPT = """## 项目描述
{project_description}

## 项目记忆
{memory_section}

## 当前状态
- 第 {round_number} 轮（共 {max_rounds} 轮）
- 可用数据源及可靠性：{tool_reliability}
- 禁用数据源（网络不可达）：{disabled_sources}
{prev_stats_section}

请生成完整的检索方案（仅输出 JSON，不要其他文字）。"""


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
    构建 QueryPlanAgent prompt。
    Returns: (system_prompt, user_prompt)
    """
    memory_section = memory_text[:800] if memory_text else "（首轮，无历史记忆）"

    # 格式化工具可靠性
    reliability_lines = []
    for tool_id, rel in sorted(tool_reliability.items()):
        if tool_id not in disabled_sources:
            rel_val = rel if isinstance(rel, (int, float)) else rel.get("reliability", 1.0) if isinstance(rel, dict) else 1.0
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

    user_prompt = QUERY_PLAN_USER_PROMPT.format(
        project_description=project_description[:600],
        memory_section=memory_section,
        round_number=round_number,
        max_rounds=max_rounds,
        tool_reliability=reliability_str,
        disabled_sources=disabled_str,
        prev_stats_section=prev_stats_section,
    )

    return QUERY_PLAN_SYSTEM_PROMPT, user_prompt
