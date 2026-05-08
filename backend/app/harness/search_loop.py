"""
Agent Search Loop — replaces the rigid "translate → search all → score" pipeline
with an intelligent observe-plan-execute-evaluate cycle.

Instead of blasting all sources with the same query, the agent:
1. OBSERVE: Analyze the topic, profile, and available tools
2. PLAN: Choose a subset of tools with tailored queries per source
3. EXECUTE: Run the chosen tools in parallel
4. EVALUATE: Check result quality (coverage, relevance, diversity)
5. ADAPT: If quality is low, adjust queries and try additional sources
6. YIELD: Return combined results

This is the S01 (The Loop) pattern from Claude Code, adapted for search.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class SearchIteration:
    """Result of one iteration within the search loop."""
    iteration: int
    sources_used: List[str]
    docs_found: int
    docs_with_abstract: int
    execution_ms: int
    quality_score: float  # 0-1

@dataclass
class LoopResult:
    """Final result of the agent search loop."""
    all_docs: List[Dict]
    total_candidates: int
    source_stats: Dict[str, Dict]
    iterations: List[SearchIteration]
    loop_rationale: str


class AgentSearchLoop:
    """
    Intelligent search loop that adapts based on result quality.

    Max 3 iterations per round to limit LLM cost.
    Each iteration can search different sources or refine queries.
    """

    MAX_ITERATIONS = 3
    MIN_QUALITY_THRESHOLD = 0.4  # Below this, try another iteration
    MIN_DOCS_THRESHOLD = 5       # Below this, always retry

    async def run(
        self,
        query_plan,
        exclude_doc_keys: Optional[Set[str]] = None,
        scoring_weights: Optional[Dict[str, float]] = None,
        llm_manager=None,
        per_source_queries: Optional[Dict[str, Any]] = None,  # {sid: {complex, medium, simple}} 或旧 {sid: str}
        dynamic_synonyms: Optional[Dict[str, List[str]]] = None,
    ) -> LoopResult:
        """
        Run the adaptive search loop.
        Falls back to single-pass if no LLM available.
        """
        from app.services.search_engine import execute_search

        iterations = []
        all_source_stats = {}
        best_docs = []
        best_candidates = 0

        # Iteration 1: Execute with the original query plan
        t0 = time.time()
        docs, candidates, stats = await execute_search(
            query_plan,
            exclude_doc_keys=exclude_doc_keys,
            scoring_weights=scoring_weights,
            per_source_queries=per_source_queries,
            dynamic_synonyms=dynamic_synonyms,
        )
        elapsed = int((time.time() - t0) * 1000)
        all_source_stats.update(stats)

        quality = self._assess_quality(docs, stats, query_plan)
        iterations.append(SearchIteration(
            iteration=1,
            sources_used=list(stats.keys()),
            docs_found=len(docs),
            docs_with_abstract=sum(1 for d in docs if d.get("abstract")),
            execution_ms=elapsed,
            quality_score=quality,
        ))

        best_docs = docs
        best_candidates = candidates

        logger.info(
            "[SearchLoop] Iter 1: %d docs, quality=%.2f, %d sources",
            len(docs), quality, len(stats),
        )

        # If quality is good enough or no LLM, return immediately
        if quality >= self.MIN_QUALITY_THRESHOLD and len(docs) >= self.MIN_DOCS_THRESHOLD:
            return LoopResult(
                all_docs=best_docs,
                total_candidates=best_candidates,
                source_stats=all_source_stats,
                iterations=iterations,
                loop_rationale=f"Single pass sufficient: quality={quality:.2f}, docs={len(docs)}",
            )

        if not llm_manager:
            return LoopResult(
                all_docs=best_docs,
                total_candidates=best_candidates,
                source_stats=all_source_stats,
                iterations=iterations,
                loop_rationale="No LLM available for adaptive iterations",
            )

        # Iteration 2+: Adaptive retry
        for i in range(2, self.MAX_ITERATIONS + 1):
            # Ask LLM how to improve
            adjustment = await self._plan_adjustment(
                query_plan, stats, docs, quality, llm_manager
            )
            if not adjustment:
                break

            # Apply adjustment: modify query or sources
            adjusted_plan = self._apply_adjustment(query_plan, adjustment)
            if not adjusted_plan:
                break

            t0 = time.time()
            new_docs, new_candidates, new_stats = await execute_search(
                adjusted_plan,
                exclude_doc_keys=exclude_doc_keys,
                scoring_weights=scoring_weights,
            )
            elapsed = int((time.time() - t0) * 1000)
            all_source_stats.update(new_stats)

            # Merge new docs (deduplicate by title)
            existing_titles = {(d.get("title") or "").lower() for d in best_docs}
            added = 0
            for d in new_docs:
                title_l = (d.get("title") or "").lower()
                if title_l and title_l not in existing_titles:
                    best_docs.append(d)
                    existing_titles.add(title_l)
                    added += 1

            best_candidates += new_candidates
            quality = self._assess_quality(best_docs, all_source_stats, query_plan)

            iterations.append(SearchIteration(
                iteration=i,
                sources_used=list(new_stats.keys()),
                docs_found=added,
                docs_with_abstract=sum(1 for d in new_docs if d.get("abstract")),
                execution_ms=elapsed,
                quality_score=quality,
            ))

            logger.info(
                "[SearchLoop] Iter %d: +%d new docs, quality=%.2f (%s)",
                i, added, quality, adjustment.get("strategy", ""),
            )

            if quality >= self.MIN_QUALITY_THRESHOLD:
                break

        rationale = (
            f"{len(iterations)} iterations, final quality={quality:.2f}, "
            f"total={len(best_docs)} docs from {len(all_source_stats)} sources"
        )

        return LoopResult(
            all_docs=best_docs,
            total_candidates=best_candidates,
            source_stats=all_source_stats,
            iterations=iterations,
            loop_rationale=rationale,
        )

    def _assess_quality(self, docs: List[Dict], stats: Dict, query_plan) -> float:
        """Score result quality 0.0 - 1.0."""
        if not docs:
            return 0.0

        scores = []

        # Factor 1: Document count (0-1, saturates at 20)
        count_score = min(len(docs) / 20, 1.0)
        scores.append(count_score * 0.3)

        # Factor 2: Abstract coverage
        with_abstract = sum(1 for d in docs if d.get("abstract"))
        abstract_rate = with_abstract / len(docs)
        scores.append(abstract_rate * 0.3)

        # Factor 3: Source diversity (0-1, saturates at 4 sources)
        active_sources = sum(1 for s in stats.values()
                            if isinstance(s, dict) and s.get("count", 0) > 0)
        diversity_score = min(active_sources / 4, 1.0)
        scores.append(diversity_score * 0.2)

        # Factor 4: Recency (fraction of docs from last 5 years)
        from datetime import datetime
        current_year = datetime.now().year
        recent = sum(1 for d in docs
                     if d.get("publication_date") and
                     str(d["publication_date"])[:4].isdigit() and
                     int(str(d["publication_date"])[:4]) >= current_year - 5)
        recency_score = recent / len(docs) if docs else 0
        scores.append(recency_score * 0.2)

        return sum(scores)

    async def _plan_adjustment(
        self, query_plan, stats, docs, quality, llm_manager
    ) -> Optional[Dict]:
        """Ask LLM how to improve search quality."""
        import json, re

        # Identify problems
        problems = []
        active = {s for s, v in stats.items() if isinstance(v, dict) and v.get("count", 0) > 0}
        if len(active) < 3:
            problems.append(f"Only {len(active)} sources returned results")
        abstract_rate = sum(1 for d in docs if d.get("abstract")) / max(len(docs), 1)
        if abstract_rate < 0.5:
            problems.append(f"Only {abstract_rate:.0%} docs have abstracts")
        if len(docs) < 10:
            problems.append(f"Only {len(docs)} docs found")

        if not problems:
            return None

        prompt = (
            f"Search quality is low ({quality:.2f}/1.0). Problems: {'; '.join(problems)}\n"
            f"Original query: {query_plan.base_query}\n"
            f"Sources that returned 0: {[s for s, v in stats.items() if isinstance(v, dict) and v.get('count', 0) == 0]}\n\n"
            "Suggest ONE adjustment (JSON):\n"
            '{"strategy": "broaden_query|add_synonyms|different_sources|relax_dates",'
            ' "new_terms": ["term1"], "remove_sources": [], "add_sources": [],'
            ' "year_adjustment": null}'
        )

        try:
            result = await llm_manager.generate(
                prompt, temperature=0.2,
                response_format={"type": "json_object"},
            )
            if result:
                match = re.search(r'\{[\s\S]*\}', result)
                if match:
                    return json.loads(match.group())
        except Exception as e:
            logger.warning("[SearchLoop] Adjustment planning failed: %s", e)

        return None

    def _apply_adjustment(self, original_plan, adjustment: Dict):
        """Create a modified query plan based on the adjustment."""
        from app.services.query_builder import QueryPlan
        import copy

        strategy = adjustment.get("strategy", "")
        new_terms = adjustment.get("new_terms", [])

        # Build modified query
        new_query = original_plan.base_query
        if new_terms:
            new_query = f"{new_query} {' '.join(new_terms)}"

        new_sources = list(original_plan.sources)
        for s in adjustment.get("remove_sources", []):
            if s in new_sources:
                new_sources.remove(s)
        for s in adjustment.get("add_sources", []):
            if s not in new_sources:
                new_sources.append(s)

        year_from = original_plan.year_from
        if adjustment.get("year_adjustment") == "broaden":
            year_from = (year_from - 5) if year_from else None

        return QueryPlan(
            base_query=new_query,
            expanded_terms=original_plan.expanded_terms + new_terms,
            exclude_terms=original_plan.exclude_terms,
            year_from=year_from,
            year_to=original_plan.year_to,
            sources=new_sources,
            max_results_per_source=original_plan.max_results_per_source,
            language_scope=original_plan.language_scope,
            original_chinese_query=original_plan.original_chinese_query,
            english_query_source=original_plan.english_query_source,
            cn_query_source=original_plan.cn_query_source,
            profile_injected_en=original_plan.profile_injected_en,
            profile_injected_zh=original_plan.profile_injected_zh,
            profile_query_extension=original_plan.profile_query_extension,
            anchor_keywords=original_plan.anchor_keywords,
        )
