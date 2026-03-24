"""
单轮检索引擎
协调 fetchers + 去重 + 打分 + 选Top-N
"""
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.services.fetchers.international import ALL_FETCHERS
from app.services.relevance_engine import select_top_documents, deduplicate_docs
from app.services.query_builder import QueryPlan


async def execute_search(
    query_plan: QueryPlan,
    progress_callback=None,
) -> tuple[List[Dict], int]:
    """
    执行单轮搜索（真正并行，与 v1 的 asyncio.gather 模式相同）
    返回: (selected_docs, total_candidates)
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
                query=" ".join(query_plan.expanded_terms),
                max_results=query_plan.max_results_per_source,
                year_from=query_plan.year_from,
                year_to=query_plan.year_to,
            )
        )
        task_sources.append(source_id)

    if not tasks:
        return [], 0

    # 真正并行执行（继承 v1 的 asyncio.gather 模式）
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_docs: List[Dict] = []
    for source_id, result in zip(task_sources, results):
        if isinstance(result, Exception):
            print(f"[SearchEngine] {source_id} 异常: {result}")
            continue
        _, docs = result
        all_docs.extend(docs)
        if progress_callback:
            await progress_callback(source_id, len(docs))

    total_candidates = len(all_docs)

    # 去重
    all_docs = deduplicate_docs(all_docs)

    # 打分并选 Top-N
    selected = select_top_documents(
        docs=all_docs,
        query_terms=query_plan.expanded_terms + (query_plan.exclude_terms or []),
        max_select=query_plan.max_results_per_source * len(task_sources),
        exclude_terms=query_plan.exclude_terms,
    )

    # 限制最终返回数量
    from app.services.query_builder import ROUND_CONFIGS
    return selected, total_candidates
