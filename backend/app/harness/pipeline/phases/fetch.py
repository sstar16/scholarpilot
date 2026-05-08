"""FetchPhase — drive AgentSearchLoop across the (mode-filtered) sources,
return selected docs, total candidates and per-source stats. Persists a
helpful zero-result message when nothing comes back."""
from __future__ import annotations

import logging

from app.harness.pipeline.types import RoundContext

logger = logging.getLogger(__name__)


class FetchPhase:
    name = "fetch"
    deps = ["apply_search_mode", "build_dedup", "load_round"]
    progress_range = (0.22, 0.40)
    can_interrupt = False  # Answer-Now check moves to RerankPhase entry

    async def execute(self, ctx: RoundContext) -> dict:
        from app.config import settings
        from app.harness.search_loop import AgentSearchLoop
        from app.services.event_bus import EventBus

        plan_out = ctx.get("plan_query")
        query_plan = plan_out["query_plan"]
        scoring_weights = ctx.get("load_round")["scoring_weights"]
        exclude_keys = ctx.get("build_dedup")["exclude_keys"]
        confirmed = ctx.get("load_confirmed_keywords")
        per_source_queries = confirmed["per_source_queries"]
        dynamic_synonyms = confirmed["dynamic_synonyms"]

        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "searching", "progress": 0.22,
            "message": f"开始检索 {len(query_plan.sources)} 个数据源...",
        })

        search_loop = AgentSearchLoop()
        loop_result = await search_loop.run(
            query_plan,
            exclude_doc_keys=exclude_keys if exclude_keys else None,
            scoring_weights=scoring_weights,
            llm_manager=ctx.llm_manager if settings.enable_agent_planning else None,
            per_source_queries=per_source_queries,
            dynamic_synonyms=dynamic_synonyms,
        )
        selected_docs = loop_result.all_docs
        total_candidates = loop_result.total_candidates
        source_stats = loop_result.source_stats

        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "searching", "progress": 0.38,
            "message": (
                f"检索完成 · 候选 {total_candidates} 篇 · "
                f"待评分 {len(selected_docs)} 篇"
            ),
        })

        if len(loop_result.iterations) > 1:
            logger.info("[Harness] Search Loop: %s", loop_result.loop_rationale)

        if not selected_docs:
            await self._record_zero_result(
                ctx,
                search_mode=ctx.get("load_round")["search_mode"],
                source_stats=source_stats,
                total_candidates=total_candidates,
            )

        return {
            "selected_docs": selected_docs,
            "total_candidates": total_candidates,
            "source_stats": source_stats,
            "iterations": loop_result.iterations,
        }

    @staticmethod
    async def _record_zero_result(ctx, *, search_mode, source_stats, total_candidates):
        import uuid
        from sqlalchemy import update
        from app.models.search_round import SearchRound

        failed = [
            sid for sid, st in (source_stats or {}).items()
            if st.get("status") == "error" or st.get("count", 0) == 0
        ]
        if search_mode == "static_db":
            msg = (
                "本地知识库中未找到匹配文献。"
                "建议：导入更多文献到知识库 / 放宽关键词 / "
                "切换到 API 或 Hybrid 模式获取外部数据源"
            )
        elif search_mode == "api":
            msg = (
                f"API 检索未返回任何结果。已尝试 {len(source_stats or {})} 个 API 源，"
                f"其中 {len(failed)} 个返回 0 篇。"
                "建议：扩大年份范围 / 放宽关键词 / 切换到 Hybrid 兼顾本地库"
            )
        else:
            msg = (
                f"检索未返回任何结果。已尝试 {len(source_stats or {})} 个源，"
                f"其中 {len(failed)} 个返回 0 篇。"
                "建议：扩大年份范围 / 放宽关键词 / 切换检索模式"
            )
        logger.warning(
            "[SearchLoop] zero results mode=%s sources=%s",
            search_mode, failed,
        )
        await ctx.db.execute(
            update(SearchRound)
            .where(SearchRound.id == uuid.UUID(ctx.round_id))
            .values(progress_message=msg, source_stats=source_stats)
        )
        await ctx.db.commit()
