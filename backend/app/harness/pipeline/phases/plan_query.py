"""PlanQueryPhase — generate the round's QueryPlan via QueryPlanAgent
(LLM) with deterministic build_query() as fallback. Persists the plan summary
to SearchRound.search_queries for the Dev View."""
from __future__ import annotations

import logging

from app.harness.pipeline.types import RoundContext

logger = logging.getLogger(__name__)


class PlanQueryPhase:
    name = "plan_query"
    deps = ["load_round", "build_dedup", "load_memory"]
    progress_range = (0.13, 0.20)
    can_interrupt = False

    async def execute(self, ctx: RoundContext) -> dict:
        import uuid

        from sqlalchemy import update

        from app.config import settings
        from app.models.search_round import SearchRound
        from app.services.event_bus import EventBus
        from app.services.query_builder import build_query

        project = ctx.project
        round_ = ctx.round
        memory = ctx.get("load_memory")
        memory_ctx = memory["combined_md"]
        preferred_keywords = memory["preferred_keywords"]
        excluded_keywords = memory["excluded_keywords"]
        prev_stats = memory["prev_stats"]

        query_plan = None
        plan_source = "fallback"

        if settings.enable_scoring_agent:
            try:
                from app.harness.agents.query_plan_agent import QueryPlanAgent
                from app.harness.tool_registry import ToolRegistry
                from app.services.query_builder import get_max_rounds

                registry = ToolRegistry.get_instance()
                qp_agent = QueryPlanAgent(llm_manager=ctx.llm_manager)
                query_plan = await qp_agent.plan(
                    project_description=project.description,
                    memory_text=memory_ctx,
                    round_number=round_.round_number,
                    max_rounds=project.max_rounds or get_max_rounds(project.search_config),
                    tool_reliability=registry.get_reliability_report(),
                    prev_source_stats=prev_stats,
                )
                if query_plan:
                    plan_source = "agent"
            except Exception as e:
                logger.warning("[QueryPlanAgent] failed, fallback to build_query: %s", e)
                query_plan = None

        if query_plan is None:
            query_plan = await build_query(
                project_description=project.description,
                project_domain=project.domain,
                round_number=round_.round_number,
                preferred_keywords=preferred_keywords,
                excluded_keywords=excluded_keywords,
                llm_manager=ctx.llm_manager,
                search_config=project.search_config,
                project_domains=project.domains,
                project_title=project.title,
            )

        EventBus.publish_sync(ctx.round_id, "agent_plan", {
            "plan_source": plan_source,
            "base_query": query_plan.base_query[:100],
            "sources": query_plan.sources,
            "year_range": f"{query_plan.year_from}-{query_plan.year_to}",
        })
        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "searching", "progress": 0.18,
            "message": f"已生成查询计划（{len(query_plan.sources)} 个数据源）",
        })

        query_plan_info = {
            "base_query": query_plan.base_query,
            "expanded_terms": query_plan.expanded_terms,
            "exclude_terms": query_plan.exclude_terms,
            "year_from": query_plan.year_from,
            "year_to": query_plan.year_to,
            "language_scope": query_plan.language_scope,
            "sources_selected": query_plan.sources,
            "max_per_source": query_plan.max_results_per_source,
            "original_chinese_query": query_plan.original_chinese_query,
            "plan_source": plan_source,
            "english_query_source": query_plan.english_query_source,
            "cn_query_source": query_plan.cn_query_source,
            "profile_injected_en": query_plan.profile_injected_en,
            "profile_injected_zh": query_plan.profile_injected_zh,
            "profile_query_extension": query_plan.profile_query_extension,
            "anchor_keywords": query_plan.anchor_keywords,
        }
        await ctx.db.execute(
            update(SearchRound)
            .where(SearchRound.id == uuid.UUID(ctx.round_id))
            .values(search_queries=query_plan_info)
        )
        await ctx.db.commit()

        return {"query_plan": query_plan, "plan_source": plan_source}
