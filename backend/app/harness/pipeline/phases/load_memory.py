"""LoadMemoryPhase — assemble the user / project memory bundle that
QueryPlanAgent and ScoringAgent feed on; also load the previous round's
source statistics for agent decision context."""
from __future__ import annotations

from app.harness.pipeline.types import RoundContext


class LoadMemoryPhase:
    name = "load_memory"
    deps = ["load_round"]
    progress_range = (0.10, 0.13)
    can_interrupt = False

    async def execute(self, ctx: RoundContext) -> dict:
        from sqlalchemy import select
        from app.models.search_round import SearchRound
        from app.services.markdown_memory import build_combined_memory_for_agents
        from app.services.profile_service import get_or_create_profile

        project = ctx.project
        round_ = ctx.round

        profile = await get_or_create_profile(project.user_id, project.id, ctx.db)
        preferred_keywords = profile.preferred_keywords or []
        excluded_keywords = profile.excluded_keywords or []

        user_proj_md = await build_combined_memory_for_agents(
            project.user_id, project.id, ctx.db,
        )
        legacy_memory = profile.memory_text or ""
        combined_md = "\n\n".join(
            x for x in (user_proj_md, legacy_memory) if x
        ).strip()

        prev_stats: dict = {}
        if round_.round_number > 1:
            prev_q = await ctx.db.execute(
                select(SearchRound).where(
                    SearchRound.project_id == project.id,
                    SearchRound.round_number == round_.round_number - 1,
                )
            )
            prev_round = prev_q.scalar_one_or_none()
            if prev_round and prev_round.source_stats:
                prev_stats = prev_round.source_stats

        return {
            "profile": profile,
            "preferred_keywords": preferred_keywords,
            "excluded_keywords": excluded_keywords,
            "combined_md": combined_md,
            "prev_stats": prev_stats,
        }
