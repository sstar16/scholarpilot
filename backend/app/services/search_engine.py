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

# 经实测中英双语都有索引的国际源 —— 根据 language_scope 自适应：
#   chinese_first → 直接用中文查询，不翻译
#   international → 用英文查询（现有行为）
#   global / bilingual → 并发跑一次中文 + 一次英文，结果合并
# 参考：2026-04-21 全源交叉测试（openalex / crossref / europe_pmc / semantic_scholar 中文查询均能召回）
_MULTILINGUAL_SOURCES = {"openalex", "crossref", "europe_pmc", "semantic_scholar"}


async def execute_search(
    query_plan: QueryPlan,
    progress_callback=None,
    exclude_doc_keys: Optional[Set[str]] = None,
    scoring_weights: Optional[Dict[str, float]] = None,
    per_source_queries: Optional[Dict[str, object]] = None,
    dynamic_synonyms: Optional[Dict[str, List[str]]] = None,
) -> tuple[List[Dict], int, Dict[str, Dict]]:
    """
    执行单轮搜索（真正并行）
    返回: (selected_docs, total_candidates, source_stats)

    per_source_queries 每源 value 支持两种格式：
      - 新: {"complex": str, "medium": str, "simple": str}  — 3 层降级
      - 旧: str  — 只有 complex 层（兼容旧 Redis payload）

    每源按 complex → medium → simple 顺序尝试，任一层返回 >0 docs 即停止；
    层间去重（相同的 query 跳过）；执行时仍保持源间并行。

    exclude_doc_keys: 跨轮去重，格式 {"source:external_id", ...}
    scoring_weights: 自定义评分权重 {"keyword": 0.6, "citation": 0.25, "recency": 0.15}
    """

    async def _single_fetch(fetcher, src_id, query, max_results, year_from, year_to):
        t0 = time.time()
        result = await fetcher.safe_fetch(
            query=query,
            max_results=max_results,
            year_from=year_from,
            year_to=year_to,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        doc_count = 0
        docs: List[Dict] = []
        try:
            _, docs = result
            doc_count = len(docs) if docs else 0
        except Exception:
            pass
        logger.info(
            "[search] %-16s years=%s-%s q=%r → %d docs (%dms)",
            src_id, year_from, year_to, (query or "")[:80], doc_count, elapsed_ms,
        )
        try:
            from app.harness.tool_registry import ToolRegistry
            registry = ToolRegistry.get_instance()
            registry.record_result(src_id, success=doc_count > 0, latency_ms=elapsed_ms)
        except Exception:
            pass
        return docs, elapsed_ms, None

    async def _fetch_with_tier_fallback(fetcher, src_id, tiers, max_results, year_from, year_to):
        """
        tiers: [(tier_name, query), ...]，按顺序尝试。
        返回 (docs, total_elapsed_ms, tier_attempts, winning_tier)
          tier_attempts: [{"tier": name, "query": q, "count": n, "ms": t}, ...]
        """
        seen_q: Set[str] = set()
        attempts: List[Dict] = []
        total_ms = 0
        winning_tier = None
        last_docs: List[Dict] = []
        for tier_name, q in tiers:
            if not q or q in seen_q:
                continue
            seen_q.add(q)
            try:
                docs, elapsed_ms, _ = await _single_fetch(
                    fetcher, src_id, q, max_results, year_from, year_to,
                )
            except Exception as e:
                attempts.append({"tier": tier_name, "query": q, "count": 0, "ms": 0, "error": str(e)[:100]})
                continue
            total_ms += elapsed_ms
            count = len(docs) if docs else 0
            attempts.append({"tier": tier_name, "query": q, "count": count, "ms": elapsed_ms})
            if count > 0:
                winning_tier = tier_name
                last_docs = docs
                break
            last_docs = docs  # 空也记一下，避免未赋值
        return last_docs, total_ms, attempts, winning_tier

    # 每源构建 fetch jobs。一个源在多语言模式下可以产生 2 个 job（EN + ZH 并发）
    # jobs: List[(source_id, lang_label, tiers)]
    jobs: List[tuple] = []

    scope = (query_plan.language_scope or "international").lower()
    chinese_q = (query_plan.original_chinese_query or "").strip()

    def _default_en_query(sid: str) -> str:
        if query_plan.profile_query_extension:
            return f"{query_plan.base_query} {query_plan.profile_query_extension}"
        return query_plan.base_query

    for source_id in query_plan.sources:
        fetcher = ALL_FETCHERS.get(source_id)
        if not fetcher:
            continue

        override = per_source_queries.get(source_id) if per_source_queries else None
        if isinstance(override, dict):
            # 用户显式给了 3 层 → 直接用，不做多语言分裂
            tiers = [
                ("complex", override.get("complex") or ""),
                ("medium", override.get("medium") or ""),
                ("simple", override.get("simple") or ""),
            ]
            tiers = [(n, q) for n, q in tiers if q]
            if not tiers:
                continue
            jobs.append((source_id, "", tiers))
            continue

        if isinstance(override, str) and override:
            jobs.append((source_id, "", [("complex", override)]))
            continue

        # 无用户 override：默认路径
        is_multi = source_id in _MULTILINGUAL_SOURCES
        if source_id in _CHINESE_SOURCES and chinese_q:
            # 纯中文源：不翻译
            jobs.append((source_id, "", [("complex", chinese_q)]))
        elif is_multi and scope == "chinese_first" and chinese_q:
            # 多语源 + 中文优先：直接用中文查询
            jobs.append((source_id, "zh", [("complex", chinese_q)]))
        elif is_multi and scope in ("global", "bilingual") and chinese_q:
            # 多语源 + 混合：中英各跑一次，并发
            jobs.append((source_id, "en", [("complex", _default_en_query(source_id))]))
            jobs.append((source_id, "zh", [("complex", chinese_q)]))
        else:
            # 默认：英文路径
            jobs.append((source_id, "", [("complex", _default_en_query(source_id))]))

    if not jobs:
        return [], 0, {}

    tasks = []
    for sid, lang_label, tiers in jobs:
        tasks.append(
            _fetch_with_tier_fallback(
                fetcher=ALL_FETCHERS[sid],
                src_id=f"{sid}.{lang_label}" if lang_label else sid,
                tiers=tiers,
                max_results=query_plan.max_results_per_source,
                year_from=query_plan.year_from,
                year_to=query_plan.year_to,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_docs: List[Dict] = []
    source_stats: Dict[str, Dict] = {}
    # jobs 与 results 按位置对齐；同一 source_id 可能出现多次（多语言分裂）
    for (source_id, lang_label, tiers), result in zip(jobs, results):
        primary_q = tiers[0][1] if tiers else ""
        job_key = source_id  # 统计按 source_id 聚合；单源多语言在 sub_lang 里分开

        if isinstance(result, Exception):
            logger.error("[SearchEngine] %s.%s 异常: %s", source_id, lang_label or "-", result)
            err_entry = {
                "status": "error", "count": 0, "error": str(result)[:200],
                "query_sent": primary_q,
                "lang": lang_label or None,
                "execution_ms": 0,
            }
            if job_key in source_stats:
                # 已有另一语言的 job 成功/在统计里 → 记到 sub_lang 不覆盖
                source_stats[job_key].setdefault("sub_lang", {})[lang_label or "default"] = err_entry
            else:
                source_stats[job_key] = {
                    **err_entry,
                    "year_from": query_plan.year_from,
                    "year_to": query_plan.year_to,
                    "max_requested": query_plan.max_results_per_source,
                }
            continue

        docs, total_ms, attempts, winning_tier = result
        all_docs.extend(docs or [])
        count = len(docs) if docs else 0
        q_sent = attempts[-1]["query"] if attempts else primary_q
        entry = {
            "status": "ok",
            "count": count,
            "query_sent": q_sent,
            "year_from": query_plan.year_from,
            "year_to": query_plan.year_to,
            "max_requested": query_plan.max_results_per_source,
            "execution_ms": total_ms,
            "tier_attempts": attempts,
            "winning_tier": winning_tier,
            "lang": lang_label or None,
        }

        if job_key in source_stats:
            # 多语言第二个 job 合并进来
            existing = source_stats[job_key]
            existing["count"] = existing.get("count", 0) + count
            existing["execution_ms"] = max(existing.get("execution_ms", 0), total_ms)
            sub = existing.setdefault("sub_lang", {})
            # 第一次合并时把前一次的单语 job 也塞到 sub_lang
            if not sub:
                sub[existing.get("lang") or "default"] = {
                    "count": existing["count"] - count,
                    "query_sent": existing.get("query_sent"),
                    "tier_attempts": existing.get("tier_attempts"),
                    "winning_tier": existing.get("winning_tier"),
                }
            sub[lang_label or "default"] = {
                "count": count,
                "query_sent": q_sent,
                "tier_attempts": attempts,
                "winning_tier": winning_tier,
            }
        else:
            source_stats[job_key] = entry

        if progress_callback:
            await progress_callback(source_id, count)

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
