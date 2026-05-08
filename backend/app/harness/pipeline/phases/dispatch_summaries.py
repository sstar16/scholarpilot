"""DispatchSummariesPhase — fan out per-doc Celery summary tasks via chord
and kick off the fire-and-forget Coordinator. Fourth Answer-Now interrupt
point (legacy stage='summarizing'). The chord callback (finalize) handles
status transition to ``awaiting_feedback`` after summaries land."""
from __future__ import annotations

import logging
import uuid

from app.harness.pipeline.types import RoundContext

logger = logging.getLogger(__name__)


class DispatchSummariesPhase:
    name = "dispatch_summaries"
    deps = ["save_docs"]
    progress_range = (0.60, 0.62)
    can_interrupt = True
    partial_stage = "summarizing"

    async def execute(self, ctx: RoundContext) -> dict:
        from celery import chord, group

        from app.services.event_bus import EventBus
        from app.services.progressive_search import mark_round_summarizing
        from app.workers.search_tasks import (
            finalize_round_after_summaries,
            generate_summary_for_doc,
            run_coordinator_async,
        )

        save_out = ctx.get("save_docs")
        docs = save_out["selected_docs"]
        total_candidates = save_out["total_candidates"]
        round_uuid = uuid.UUID(ctx.round_id)
        project = ctx.project

        await mark_round_summarizing(
            round_uuid, total_candidates, len(docs), ctx.db,
            source_stats=ctx.get("fetch")["source_stats"],
        )

        EventBus.publish_sync(ctx.round_id, "round_status", {
            "status": "summarizing", "progress": 0.62,
            "message": f"正在为 {len(docs)} 篇文献生成 AI 摘要...",
        })
        for d in docs:
            EventBus.publish_sync(ctx.round_id, "doc_arrived", {
                "external_id": str(d.get("external_id", "")),
                "source": d.get("source"),
                "title": d.get("title", ""),
                "doc_type": d.get("doc_type", "paper"),
                "has_abstract": bool(d.get("abstract")),
            })

        summary_tasks = [
            generate_summary_for_doc.s(
                round_id_str=ctx.round_id,
                source=d.get("source"),
                external_id=str(d.get("external_id", "")),
                project_description=project.description,
                session_id=ctx.session_id,
            )
            for d in docs
        ]

        try:
            run_coordinator_async.delay(ctx.round_id)
        except Exception as e:
            logger.warning("[Harness] Coordinator dispatch failed (non-fatal): %s", e)

        callback = finalize_round_after_summaries.si(round_id_str=ctx.round_id)
        chord(group(summary_tasks))(callback)

        return {
            "selected": len(docs),
            "total": total_candidates,
            "dispatched": True,
        }
