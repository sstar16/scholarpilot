"""BuildDedupPhase — collect (source, external_id) pairs that must be
excluded from the next fetch: prior-round documents + user negative feedback."""
from __future__ import annotations

from app.harness.pipeline.types import RoundContext


class BuildDedupPhase:
    name = "build_dedup"
    deps = ["load_round"]
    progress_range = (0.08, 0.10)
    can_interrupt = False

    async def execute(self, ctx: RoundContext) -> dict:
        from sqlalchemy import select
        from app.models.document import Document
        from app.models.feedback import Feedback
        from app.models.round_document import RoundDocument
        from app.models.search_round import SearchRound

        project_id = ctx.project.id

        prev = await ctx.db.execute(
            select(Document.source, Document.external_id)
            .join(RoundDocument, RoundDocument.document_id == Document.id)
            .join(SearchRound, SearchRound.id == RoundDocument.round_id)
            .where(SearchRound.project_id == project_id)
        )
        exclude_keys = {f"{row[0]}:{row[1]}" for row in prev.all()}

        neg = await ctx.db.execute(
            select(Document.source, Document.external_id)
            .join(Feedback, Feedback.document_id == Document.id)
            .where(
                Feedback.round_id.in_(
                    select(SearchRound.id).where(SearchRound.project_id == project_id)
                ),
                Feedback.relevance == -1,
            )
        )
        for row in neg.all():
            exclude_keys.add(f"{row[0]}:{row[1]}")

        return {"exclude_keys": exclude_keys}
