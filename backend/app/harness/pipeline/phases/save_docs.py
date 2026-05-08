"""SaveDocsPhase — persist Document + RoundDocument rows. Third Answer-Now
interrupt point (legacy stage='saving'). Aborts the round (not as failure)
when the score phase produced zero documents."""
from __future__ import annotations

import uuid

from app.harness.pipeline.types import PhaseAborted, RoundContext


class SaveDocsPhase:
    name = "save_docs"
    deps = ["score", "fetch"]
    progress_range = (0.52, 0.60)
    can_interrupt = True
    partial_stage = "saving"

    async def execute(self, ctx: RoundContext) -> dict:
        from sqlalchemy import update

        from app.models.search_round import SearchRound
        from app.services.event_bus import EventBus
        from app.services.progressive_search import (
            mark_round_awaiting_feedback,
            save_round_documents,
        )

        fetch_out = ctx.get("fetch")
        score_out = ctx.get("score")
        score_docs = (score_out or {}).get("selected_docs") if score_out else None
        # When score was skipped (no docs), score_out is None.
        docs = score_docs if score_docs is not None else fetch_out["selected_docs"]

        round_uuid = uuid.UUID(ctx.round_id)
        total_candidates = fetch_out["total_candidates"]
        source_stats = fetch_out["source_stats"]

        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "saving", "progress": 0.52,
            "message": f"AI 评分完成，{len(docs)} 篇通过筛选",
        })

        if not docs:
            await ctx.db.execute(
                update(SearchRound)
                .where(SearchRound.id == round_uuid)
                .values(
                    source_stats=source_stats,
                    total_candidates=total_candidates,
                )
            )
            await ctx.db.commit()
            await mark_round_awaiting_feedback(round_uuid, ctx.db)
            raise PhaseAborted(
                "zero_results",
                payload={"selected": 0, "total": total_candidates},
            )

        await save_round_documents(round_uuid, docs, ctx.db)
        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "saving", "progress": 0.58,
            "message": f"已保存 {len(docs)} 篇文献到本轮",
        })

        return {
            "selected_docs": docs,
            "selected_count": len(docs),
            "total_candidates": total_candidates,
        }
