"""RerankPhase — optional LLM-based rerank gated on
``project.search_config.enable_llm_rerank``. Acts as the first Answer-Now
interrupt point (legacy stage='searching')."""
from __future__ import annotations

from app.harness.pipeline.types import PhaseSkipped, RoundContext


class RerankPhase:
    name = "rerank"
    deps = ["fetch"]
    progress_range = (0.40, 0.42)
    can_interrupt = True
    partial_stage = "searching"

    async def execute(self, ctx: RoundContext) -> dict:
        from app.services.llm_reranker import llm_rerank

        fetch_out = ctx.get("fetch")
        docs = fetch_out["selected_docs"]
        if not docs:
            raise PhaseSkipped("no docs to rerank")

        cfg = ctx.project.search_config
        if not (isinstance(cfg, dict) and cfg.get("enable_llm_rerank")):
            return {"selected_docs": docs, "reranked": False}

        reranked = await llm_rerank(
            docs=docs,
            project_description=ctx.project.description,
            llm_manager=ctx.llm_manager,
        )
        return {"selected_docs": reranked, "reranked": True}
