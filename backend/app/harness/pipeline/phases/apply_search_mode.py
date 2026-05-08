"""ApplySearchModePhase — narrow query_plan.sources by search_mode
(static_db / api / hybrid). Mutates query_plan in place."""
from __future__ import annotations

import logging

from app.harness.pipeline.types import RoundContext

logger = logging.getLogger(__name__)


class ApplySearchModePhase:
    name = "apply_search_mode"
    deps = ["plan_query", "load_confirmed_keywords"]
    progress_range = (0.21, 0.22)
    can_interrupt = False

    async def execute(self, ctx: RoundContext) -> dict:
        query_plan = ctx.get("plan_query")["query_plan"]
        search_mode = ctx.get("load_round")["search_mode"]
        per_source_queries = ctx.get("load_confirmed_keywords")["per_source_queries"]

        if search_mode == "static_db":
            query_plan.sources = [s for s in query_plan.sources if s == "local_kb"]
            if not query_plan.sources:
                query_plan.sources = ["local_kb"]
            logger.info("[SearchMode] static_db — local KB only")
        elif search_mode == "api":
            query_plan.sources = [s for s in query_plan.sources if s != "local_kb"]
            logger.info(
                "[SearchMode] api — %d API sources, no local KB",
                len(query_plan.sources),
            )
        elif search_mode == "hybrid":
            # Honour the user's confirmed selection verbatim. Only auto-inject
            # local_kb on the legacy path (no per-source confirmation).
            if not per_source_queries and "local_kb" not in query_plan.sources:
                query_plan.sources.insert(0, "local_kb")
            logger.info(
                "[SearchMode] hybrid — %d sources",
                len(query_plan.sources),
            )

        return {"final_sources": list(query_plan.sources)}
