"""
单轮检索引擎
协调 fetchers + 去重 + 打分 + 选Top-N
"""
import asyncio
import logging
import time
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
    profile_embedding: Optional[List[float]] = None,
    per_source_queries: Optional[Dict[str, str]] = None,
    dynamic_synonyms: Optional[Dict[str, List[str]]] = None,
) -> tuple[List[Dict], int, Dict[str, Dict]]:
    """
    执行单轮搜索（真正并行）
    返回: (selected_docs, total_candidates, source_stats)

    exclude_doc_keys: 跨轮去重，格式 {"source:external_id", ...}
    scoring_weights: 自定义评分权重 {"keyword": 0.6, "citation": 0.25, "recency": 0.15}
    """

    # 构建并行任务（带计时包装）
    tasks = []
    task_sources = []
    queries_per_source: Dict[str, str] = {}

    async def _timed_fetch(fetcher, src_id, query, max_results, year_from, year_to):
        t0 = time.time()
        result = await fetcher.safe_fetch(
            query=query,
            max_results=max_results,
            year_from=year_from,
            year_to=year_to,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        # Record stats in tool registry (no-op if registry not initialized)
        try:
            from app.harness.tool_registry import ToolRegistry
            registry = ToolRegistry.get_instance()
            _, docs = result
            registry.record_result(src_id, success=len(docs) > 0 or True, latency_ms=elapsed_ms)
        except Exception:
            pass
        return result, elapsed_ms

    for source_id in query_plan.sources:
        fetcher = ALL_FETCHERS.get(source_id)
        if not fetcher:
            continue
        # Per-source 查询词优先（用户确认后的定制查询）
        if per_source_queries and source_id in per_source_queries:
            query = per_source_queries[source_id]
        # 中文数据源用原始中文查询词（含中文画像词追加）；
        # 英文数据源 round>=3 时追加 profile_query_extension 扩大召回
        elif source_id in _CHINESE_SOURCES and query_plan.original_chinese_query:
            query = query_plan.original_chinese_query
        elif query_plan.profile_query_extension:
            query = f"{query_plan.base_query} {query_plan.profile_query_extension}"
        else:
            query = query_plan.base_query
        queries_per_source[source_id] = query
        tasks.append(
            _timed_fetch(
                fetcher=fetcher,
                src_id=source_id,
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
        query_sent = queries_per_source.get(source_id, "")
        if isinstance(result, Exception):
            logger.error("[SearchEngine] %s 异常: %s", source_id, result)
            source_stats[source_id] = {
                "status": "error", "count": 0, "error": str(result)[:200],
                "query_sent": query_sent,
                "year_from": query_plan.year_from,
                "year_to": query_plan.year_to,
                "max_requested": query_plan.max_results_per_source,
                "execution_ms": 0,
            }
            continue
        (_, docs), elapsed_ms = result
        all_docs.extend(docs)
        source_stats[source_id] = {
            "status": "ok",
            "count": len(docs),
            "query_sent": query_sent,
            "year_from": query_plan.year_from,
            "year_to": query_plan.year_to,
            "max_requested": query_plan.max_results_per_source,
            "execution_ms": elapsed_ms,
        }
        if progress_callback:
            await progress_callback(source_id, len(docs))

    logger.info("[SearchEngine] 数据源统计: %s", {k: v["count"] for k, v in source_stats.items()})

    total_candidates = len(all_docs)

    # 去重
    all_docs = deduplicate_docs(all_docs)

    # 元数据补全（对缺少摘要的文档尝试从 OpenAlex/Crossref 补全）
    all_docs = await enrich_missing_abstracts(all_docs)

    # 传统评分（计算 _relevance_score 用作排序参考和 LLM fallback，但不截断）
    selected = select_top_documents(
        docs=all_docs,
        query_terms=query_plan.expanded_terms,
        max_select=len(all_docs),  # 不截断，全量送 Scoring Agent
        exclude_terms=query_plan.exclude_terms,
        exclude_doc_keys=exclude_doc_keys,
        scoring_weights=scoring_weights,
        profile_embedding=profile_embedding,
        dynamic_synonyms=dynamic_synonyms,
    )

    # 保底机制：若跨轮去重后 0 篇，放宽条件重试
    if not selected and all_docs:
        logger.warning("[SearchEngine] 去重后 0 篇结果，放宽条件重试（忽略跨轮去重）")
        selected = select_top_documents(
            docs=all_docs,
            query_terms=query_plan.expanded_terms,
            max_select=len(all_docs),
            exclude_terms=None,
            exclude_doc_keys=None,
            scoring_weights=scoring_weights,
            dynamic_synonyms=dynamic_synonyms,
        )

    return selected, total_candidates, source_stats
