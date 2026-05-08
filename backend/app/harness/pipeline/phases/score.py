"""ScorePhase — LLM-based per-doc relevance scoring with cutoff filtering.
Second Answer-Now interrupt point (legacy stage='scoring')."""
from __future__ import annotations

import logging

from app.harness.pipeline.types import PhaseSkipped, RoundContext

logger = logging.getLogger(__name__)


class ScorePhase:
    name = "score"
    deps = ["rerank", "load_memory", "load_round"]
    progress_range = (0.42, 0.52)
    can_interrupt = True
    partial_stage = "scoring"

    async def execute(self, ctx: RoundContext) -> dict:
        from app.config import settings
        from app.harness.agents.scoring_agent import ScoringAgent
        from app.services.event_bus import EventBus

        rerank_out = ctx.get("rerank")
        # PhaseSkipped earlier → ctx.artifacts['rerank'] is None
        docs = (rerank_out or {}).get("selected_docs") or []
        if not docs:
            raise PhaseSkipped("no docs to score")
        if not settings.enable_scoring_agent:
            return {
                "selected_docs": docs,
                "above_cutoff": docs,
                "below_cutoff": [],
                "cutoff": None,
                "skipped": True,
            }

        cutoff = ctx.get("load_round")["scoring_cutoff"]
        if cutoff is None:
            cutoff = settings.scoring_cutoff_default

        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "scoring", "progress": 0.45,
            "message": f"AI 正在评估 {len(docs)} 篇文献相关性...",
        })

        memory = ctx.get("load_memory")["combined_md"]
        project = ctx.project
        scoring_desc = (
            f"【{project.title}】{project.description}"
            if project.title else project.description
        )

        try:
            agent = ScoringAgent(llm_manager=ctx.llm_manager)
            above, below = await agent.score_all(
                docs=docs,
                project_description=scoring_desc,
                cutoff=cutoff,
                user_memory=memory,
            )
            EventBus.publish_sync(ctx.round_id, "scoring_complete", {
                "above_cutoff": len(above),
                "below_cutoff": len(below),
                "cutoff": cutoff,
            })
            logger.info(
                "[ScoringAgent] Round %s: %d above / %d below cutoff (%.1f)",
                ctx.round_id[:8], len(above), len(below), cutoff,
            )
            return {
                "selected_docs": above + below,
                "above_cutoff": above,
                "below_cutoff": below,
                "cutoff": cutoff,
                "skipped": False,
            }
        except Exception as e:
            logger.warning(
                "[ScoringAgent] failed, falling back to legacy scores: %s", e,
            )
            return {
                "selected_docs": docs,
                "above_cutoff": docs,
                "below_cutoff": [],
                "cutoff": cutoff,
                "skipped": True,
                "error": str(e),
            }
