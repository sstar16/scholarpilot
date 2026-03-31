"""
单轮检索引擎
协调 fetchers + 去重 + 打分 + 选Top-N
"""
import asyncio
import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

from app.services.fetchers.international import ALL_FETCHERS
from app.services.fetchers.base import FetcherRegistry
from app.services.relevance_engine import select_top_documents, deduplicate_docs
from app.services.metadata_enricher import enrich_missing_abstracts
from app.services.query_builder import QueryPlan

# 这些数据源使用原始中文查询词（不翻译）
_CHINESE_SOURCES = {
    k for k, v in FetcherRegistry.SOURCES.items() if v.get("language") == "zh"
} | {"openalex_zh"}  # openalex_zh 也使用原始中文查询词


async def execute_search(
    query_plan: QueryPlan,
    progress_callback=None,
    exclude_doc_keys: Optional[Set[str]] = None,
    scoring_weights: Optional[Dict[str, float]] = None,
) -> tuple[List[Dict], int, Dict[str, Dict]]:
    """
    执行单轮搜索（真正并行）
    返回: (selected_docs, total_candidates, source_stats)

    exclude_doc_keys: 跨轮去重，格式 {"source:external_id", ...}
    scoring_weights: 自定义评分权重 {"keyword": 0.6, "citation": 0.25, "recency": 0.15}
    """

    # 构建并行任务
    tasks = []
    task_sources = []
    for source_id in query_plan.sources:
        fetcher = ALL_FETCHERS.get(source_id)
        if not fetcher:
            continue
        # 中文数据源优先使用原始中文查询词，英文数据源使用翻译后的查询词
        query = (
            query_plan.original_chinese_query or query_plan.base_query
            if source_id in _CHINESE_SOURCES and query_plan.original_chinese_query
            else query_plan.base_query
        )
        tasks.append(
            fetcher.safe_fetch(
                query=query,
                max_results=query_plan.max_results_per_source,
                year_from=query_plan.year_from,
                year_to=query_plan.year_to,
            )
        )
        task_sources.append(source_id)

    if not tasks:
        return [], 0, {}

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_docs: List[Dict] = []
    source_stats: Dict[str, Dict] = {}
    for source_id, result in zip(task_sources, results):
        if isinstance(result, Exception):
            logger.error("[SearchEngine] %s 异常: %s", source_id, result)
            source_stats[source_id] = {"status": "error", "count": 0, "error": str(result)[:200]}
            continue
        _, docs = result
        all_docs.extend(docs)
        source_stats[source_id] = {"status": "ok", "count": len(docs)}
        if progress_callback:
            await progress_callback(source_id, len(docs))

    logger.info("[SearchEngine] 数据源统计: %s", {k: v["count"] for k, v in source_stats.items()})

    total_candidates = len(all_docs)

    # 去重
    all_docs = deduplicate_docs(all_docs)

    # 元数据补全（对缺少摘要的文档尝试从 OpenAlex/Crossref 补全）
    all_docs = await enrich_missing_abstracts(all_docs)

    # 打分并选 Top-N（支持跨轮去重和综合评分）
    max_select = query_plan.max_results_per_source * len(task_sources)
    selected = select_top_documents(
        docs=all_docs,
        query_terms=query_plan.expanded_terms,
        max_select=max_select,
        exclude_terms=query_plan.exclude_terms,
        exclude_doc_keys=exclude_doc_keys,
        scoring_weights=scoring_weights,
    )

    # 保底机制：若评分后 0 篇但有候选文档，放宽条件重试
    if not selected and all_docs:
        logger.warning("[SearchEngine] 评分后 0 篇结果，放宽条件重试（忽略跨轮去重）")
        selected = select_top_documents(
            docs=all_docs,
            query_terms=query_plan.expanded_terms,
            max_select=min(3, max_select),
            exclude_terms=None,
            exclude_doc_keys=None,
            scoring_weights=scoring_weights,
        )

    return selected, total_candidates, source_stats
