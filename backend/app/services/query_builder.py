"""
查询词构建器
基于项目描述 + 用户画像，构建各轮次的实际查询词
"""
import re
from dataclasses import dataclass
from typing import List, Optional


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


def build_query(
    project_description: str,
    project_domain: str,
    round_number: int,
    preferred_keywords: Optional[List[str]] = None,
    excluded_keywords: Optional[List[str]] = None,
    preferred_sources: Optional[List[str]] = None,
) -> QueryPlan:
    """
    为指定轮次构建查询计划
    """
    from datetime import datetime
    config = ROUND_CONFIGS.get(round_number, ROUND_CONFIGS[3])

    # 提取核心关键词（简单启发式：取描述前200字的主要名词短语）
    base_query = _extract_core_query(project_description)

    # 叠加用户偏好关键词（从第2轮开始生效）
    extra = preferred_keywords[:5] if preferred_keywords and round_number > 1 else []
    expanded_terms = [base_query] + extra

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
    # 用前8个关键词构成查询
    return " ".join(meaningful[:8]) if meaningful else text[:80]


def _select_sources(scope: str, domain: str, preferred_sources: Optional[List[str]], round_number: int) -> List[str]:
    """根据范围和领域选择数据源"""
    # Phase 1 核心来源
    international_sources = ["pubmed", "openalex", "semantic_scholar", "europe_pmc"]

    # 根据领域补充专用来源
    domain_lower = domain.lower()
    if any(k in domain_lower for k in ["cs", "computer", "计算机", "ai", "machine"]):
        international_sources.append("arxiv")
    elif any(k in domain_lower for k in ["bio", "生物", "医学", "medicine", "pharmacology", "药"]):
        international_sources.extend(["biorxiv", "medrxiv"])
    elif any(k in domain_lower for k in ["physics", "物理", "math", "数学", "economics", "经济"]):
        international_sources.append("arxiv")
    else:
        # 通用：都加上 arXiv
        international_sources.append("arxiv")

    # Phase 1: chinese_first 用国际来源（中文专用来源在 Phase 2 实现）
    if scope in ("chinese_first", "international"):
        sources = international_sources
    else:
        sources = international_sources  # Phase 3 会扩展

    # 优先使用用户偏好来源
    if preferred_sources and round_number > 1:
        sources = sorted(sources, key=lambda s: 0 if s in preferred_sources else 1)

    return sources
