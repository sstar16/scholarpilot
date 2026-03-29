"""
查询词构建器
基于项目描述 + 用户画像，构建各轮次的实际查询词
"""
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


ROUND_CONFIGS = {
    1: {"years": 5,  "max_results": 10, "scope": "chinese_first"},
    2: {"years": 10, "max_results": 10, "scope": "chinese_first"},
    3: {"years": 20, "max_results": 20, "scope": "international"},
    4: {"years": None, "max_results": 200, "scope": "international"},
    5: {"years": None, "max_results": 200, "scope": "global", "translate_summary": True},
}


@dataclass
class QueryPlan:
    base_query: str
    expanded_terms: List[str]
    exclude_terms: List[str]
    year_from: Optional[int]
    year_to: Optional[int]
    sources: List[str]
    max_results_per_source: int
    language_scope: str  # chinese_first | international | global


async def build_query(
    project_description: str,
    project_domain: str,
    round_number: int,
    preferred_keywords: Optional[List[str]] = None,
    excluded_keywords: Optional[List[str]] = None,
    preferred_sources: Optional[List[str]] = None,
    llm_manager=None,
) -> QueryPlan:
    """
    为指定轮次构建查询计划。
    若提供 llm_manager 且描述主要为中文，则用 LLM 将描述翻译为英文关键词。
    """
    from datetime import datetime
    config = ROUND_CONFIGS.get(round_number, ROUND_CONFIGS[3])

    # 提取/翻译核心关键词
    base_query = await _get_english_query(project_description, llm_manager)

    # 将 base_query 拆成单词列表，确保评分引擎能逐词匹配
    base_terms = [t for t in base_query.split() if len(t) > 2]
    # 叠加用户偏好关键词（从第2轮开始生效）
    extra = preferred_keywords[:5] if preferred_keywords and round_number > 1 else []
    expanded_terms = base_terms + extra

    # 排除关键词
    exclude_terms = excluded_keywords[:3] if excluded_keywords else []

    # 年份范围
    current_year = datetime.now().year
    year_from = (current_year - config["years"]) if config["years"] else None
    year_to = current_year

    # 数据源选择
    scope = config["scope"]
    sources = _select_sources(scope, project_domain, preferred_sources, round_number)

    max_results_per_source = max(5, config["max_results"] // max(len(sources), 1))

    return QueryPlan(
        base_query=base_query,
        expanded_terms=expanded_terms,
        exclude_terms=exclude_terms,
        year_from=year_from,
        year_to=year_to,
        sources=sources,
        max_results_per_source=max_results_per_source,
        language_scope=scope,
    )


def _extract_core_query(description: str) -> str:
    """从项目描述提取核心查询词（简化版：取前150字并清理）"""
    text = description[:150].strip()
    # 去除常见停用词
    stop_words = {"的", "了", "在", "是", "和", "与", "研究", "开发", "项目", "我们"}
    # 保留较长的词作为关键词
    words = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', text)
    meaningful = [w for w in words if w not in stop_words]
    # 用前4个关键词构成查询（短查询命中率更高）
    return " ".join(meaningful[:4]) if meaningful else text[:40]


def _is_mostly_chinese(text: str) -> bool:
    """判断文本是否主要为中文（中文字符占比超过30%）"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return chinese_chars > len(text) * 0.3


async def _get_english_query(description: str, llm_manager) -> str:
    """
    获取英文搜索查询词。
    若描述主要为中文且有 LLM 可用，则翻译；否则直接提取。
    """
    if not _is_mostly_chinese(description) or llm_manager is None:
        return _extract_core_query(description)

    prompt = (
        "You are an academic search query generator. "
        "Extract 6-8 concise English keywords suitable for searching PubMed, arXiv, and OpenAlex "
        "from the following Chinese research description. "
        "Return ONLY a JSON array of strings, no explanation.\n\n"
        f"Description: {description[:400]}\n\n"
        'Example output: ["keyword1 keyword2", "keyword3", "keyword4"]'
    )
    try:
        result = await llm_manager.generate(prompt, temperature=0.1)
        if result:
            match = re.search(r'\[.*?\]', result, re.DOTALL)
            if match:
                import json as _json
                keywords = _json.loads(match.group())
                if keywords and isinstance(keywords, list) and len(keywords) >= 2:
                    # Flatten all keyword phrases into individual words, keep max 4
                    # Shorter queries have much higher hit rates on academic APIs
                    all_words = []
                    for kw in keywords:
                        all_words.extend(str(kw).split())
                    query = " ".join(all_words[:4])
                    logger.debug("[QueryBuilder] LLM翻译查询: %s", query[:100])
                    return query
    except Exception as e:
        logger.warning("[QueryBuilder] LLM翻译失败，回退到原始提取: %s", e)

    return _extract_core_query(description)


def _select_sources(scope: str, domain: str, preferred_sources: Optional[List[str]], round_number: int) -> List[str]:
    """根据范围和领域选择数据源"""
    import os
    # 通过环境变量禁用不可访问的数据源，逗号分隔，e.g. DISABLED_SOURCES=pubmed,biorxiv
    disabled = {s.strip() for s in os.getenv("DISABLED_SOURCES", "").split(",") if s.strip()}

    # Phase 1 核心来源
    international_sources = [s for s in ["pubmed", "openalex", "semantic_scholar", "europe_pmc"] if s not in disabled]

    # 根据领域补充专用来源（同样过滤 disabled）
    def _add(src):
        if src not in disabled:
            international_sources.append(src)

    domain_lower = domain.lower()
    if any(k in domain_lower for k in ["cs", "computer", "计算机", "ai", "machine"]):
        _add("arxiv")
    elif any(k in domain_lower for k in ["bio", "生物", "医学", "medicine", "pharmacology", "药"]):
        _add("biorxiv"); _add("medrxiv")
    elif any(k in domain_lower for k in ["mechanical", "机械", "设备", "automation", "自动化", "manufacturing", "制造"]):
        _add("arxiv")
    elif any(k in domain_lower for k in ["physics", "物理", "math", "数学", "economics", "经济"]):
        _add("arxiv")
    else:
        _add("arxiv")

    # Phase 1: chinese_first 用国际来源（中文专用来源在 Phase 2 实现）
    if scope in ("chinese_first", "international"):
        sources = international_sources
    else:
        sources = international_sources  # Phase 3 会扩展

    # 优先使用用户偏好来源
    if preferred_sources and round_number > 1:
        sources = sorted(sources, key=lambda s: 0 if s in preferred_sources else 1)

    return sources
