"""LoadConfirmedKeywordsPhase — read the user-confirmed keyword plan from
Redis (set by /rounds/{id}/confirm-keywords) and merge it into QueryPlan.

Mutates ``ctx.get('plan_query')['query_plan']`` in place: this is intentional
— LoadConfirmedKeywords is a strict overlay on PlanQuery's output, not a
parallel branch. Returns the per-source query map and dynamic synonyms for
downstream phases."""
from __future__ import annotations

import logging

from app.harness.pipeline.types import RoundContext

logger = logging.getLogger(__name__)


class LoadConfirmedKeywordsPhase:
    name = "load_confirmed_keywords"
    deps = ["plan_query"]
    progress_range = (0.20, 0.21)
    can_interrupt = False

    async def execute(self, ctx: RoundContext) -> dict:
        import json

        import redis.asyncio as aioredis

        from app.config import settings

        per_source_queries: dict | None = None
        dynamic_synonyms: dict | None = None

        if not settings.enable_per_source_keywords:
            return {"per_source_queries": None, "dynamic_synonyms": None}

        query_plan = ctx.get("plan_query")["query_plan"]
        try:
            r = aioredis.from_url(settings.redis_url)
            try:
                raw = await r.get(f"keyword_plan:{ctx.round_id}")
                if not raw:
                    return {"per_source_queries": None, "dynamic_synonyms": None}
                plan_data = json.loads(raw)
                if plan_data.get("confirmed"):
                    per_source_queries = {}
                    for p in plan_data.get("source_plans", []):
                        if not p.get("enabled", True):
                            continue
                        sid = p["source_id"]
                        per_source_queries[sid] = {
                            "complex": p.get("query") or "",
                            "medium": p.get("query_medium") or "",
                            "simple": p.get("query_simple") or "",
                        }
                    if per_source_queries:
                        # Respect user's enabled set verbatim — see comment in
                        # legacy code re: not intersecting with agent plan
                        # (would drop sources the user explicitly enabled).
                        query_plan.sources = list(per_source_queries.keys())
                        logger.info(
                            "[PerSourceKW] %d sources confirmed (3-tier)",
                            len(per_source_queries),
                        )
                    if "base_query" in plan_data:
                        query_plan.base_query = plan_data["base_query"]
                        query_plan.expanded_terms = [
                            w for w in plan_data["base_query"].split() if len(w) >= 2
                        ]
                        logger.info(
                            "[UserOverride] base_query → %s",
                            query_plan.base_query[:60],
                        )
                    for k in (
                        "original_chinese_query", "exclude_terms",
                        "year_from", "year_to", "max_per_source",
                        "language_scope",
                    ):
                        if k in plan_data:
                            attr = "max_results_per_source" if k == "max_per_source" else k
                            setattr(query_plan, attr, plan_data[k])
                dynamic_synonyms = plan_data.get("synonyms")
                if dynamic_synonyms:
                    logger.info(
                        "[PerSourceKW] %d synonym groups loaded",
                        len(dynamic_synonyms),
                    )
            finally:
                await r.close()
        except Exception as e:
            logger.warning("[PerSourceKW] failed to load confirmed plan: %s", e)

        return {
            "per_source_queries": per_source_queries,
            "dynamic_synonyms": dynamic_synonyms,
        }
