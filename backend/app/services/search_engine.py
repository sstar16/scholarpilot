"""
单轮检索引擎
协调 fetchers + 去重 + 打分 + 选Top-N
"""
import asyncio
import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

from app.services.fetchers.international import ALL_FETCHERS
from app.services.relevance_engine import select_top_documents, deduplicate_docs
from app.services.query_builder import QueryPlan


async def execute_search(
    query_plan: QueryPlan,
    progress_callback=None,
    exclude_doc_keys: Optional[Set[str]] = None,
    scoring_weights: Optional[Dict[str, float]] = None,
) -> tuple[List[Dict], int]:
    """
    执行单轮搜索（真正并行）
    返回: (selected_docs, total_candidates)

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
        tasks.append(
            fetcher.safe_fetch(
                query=query_plan.base_query,
                max_results=query_plan.max_results_per_source,
                year_from=query_plan.year_from,
                year_to=query_plan.year_to,
            )
        )
        task_sources.append(source_id)

    if not tasks:
        return [], 0

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_docs: List[Dict] = []
    for source_id, result in zip(task_sources, results):
        if isinstance(result, Exception):
            logger.error("[SearchEngine] %s 异常: %s", source_id, result)
            continue
        _, docs = result
        all_docs.extend(docs)
        if progress_callback:
            await progress_callback(source_id, len(docs))

    total_candidates = len(all_docs)

    # 去重
    all_docs = deduplicate_docs(all_docs)

    # 打分并选 Top-N（支持跨轮去重和综合评分）
    selected = select_top_documents(
        docs=all_docs,
        query_terms=query_plan.expanded_terms + (query_plan.exclude_terms or []),
        max_select=query_plan.max_results_per_source * len(task_sources),
        exclude_terms=query_plan.exclude_terms,
        exclude_doc_keys=exclude_doc_keys,
        scoring_weights=scoring_weights,
    )

    return selected, total_candidates
