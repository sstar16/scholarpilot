"""LoadRoundPhase — fetch SearchRound + Project, set LLM context,
mark the round as searching."""
from __future__ import annotations

import logging
import uuid

from app.harness.pipeline.types import PhaseAborted, RoundContext

logger = logging.getLogger(__name__)


class LoadRoundPhase:
    name = "load_round"
    deps: list[str] = []
    progress_range = (0.04, 0.08)
    can_interrupt = False

    async def execute(self, ctx: RoundContext) -> dict:
        from sqlalchemy import select
        from app.models.conversation_session import ConversationSession
        from app.models.project import Project
        from app.models.search_round import SearchRound
        from app.services.core.llm_context import LLMContext, set_llm_context
        from app.services.event_bus import EventBus
        from app.services.progressive_search import mark_round_searching

        round_uuid = uuid.UUID(ctx.round_id)
        r = await ctx.db.execute(
            select(SearchRound).where(SearchRound.id == round_uuid)
        )
        round_ = r.scalar_one_or_none()
        if not round_:
            raise PhaseAborted("round_not_found", payload={"error": "Round not found"})
        ctx.round = round_

        p = await ctx.db.execute(
            select(Project).where(Project.id == round_.project_id)
        )
        project = p.scalar_one_or_none()
        if not project:
            raise PhaseAborted("project_not_found",
                               payload={"error": "Project not found"})
        ctx.project = project

        # Active conversation session — used by Workbench token tracking.
        try:
            cs = await ctx.db.execute(
                select(ConversationSession.id)
                .where(
                    ConversationSession.project_id == project.id,
                    ConversationSession.is_active == True,  # noqa: E712
                )
                .order_by(ConversationSession.updated_at.desc())
                .limit(1)
            )
            sid = cs.scalar_one_or_none()
            if sid:
                ctx.session_id = str(sid)
        except Exception:
            pass

        set_llm_context(LLMContext(
            session_id=ctx.session_id,
            round_id=ctx.round_id,
            agent_name="SearchRound",
        ))

        await mark_round_searching(round_uuid, ctx.db)
        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "searching",
            "progress": 0.08,
            "message": "正在加载用户画像与项目记忆...",
        })

        # Pre-compute scoring config so later phases don't re-parse search_config.
        scoring_weights = None
        scoring_cutoff = None
        search_mode = None
        if isinstance(project.search_config, dict):
            scoring_weights = project.search_config.get("scoring_weights")
            if "scoring_cutoff" in project.search_config:
                try:
                    scoring_cutoff = float(project.search_config["scoring_cutoff"])
                except (TypeError, ValueError):
                    scoring_cutoff = None
            search_mode = project.search_config.get("search_mode")
        logger.info("[SearchMode] %s", search_mode)

        return {
            "round": round_,
            "project": project,
            "scoring_weights": scoring_weights,
            "scoring_cutoff": scoring_cutoff,
            "search_mode": search_mode,
        }
