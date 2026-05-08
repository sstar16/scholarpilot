#!/usr/bin/env python3
"""Record a real round to a JSON fixture for round-level parity testing.

ONE-TIME OPERATIONAL TOOL — runs against a real environment (postgres +
redis + real fetcher API keys) and dumps every fetcher.fetch() response and
every llm_manager.generate() response into a single JSON file.

Workflow::

    # In docker compose (real fetchers + LLM):
    docker compose exec backend python -m tests.parity.record_round \\
        --project-id <real-project-uuid> \\
        --output tests/parity/fixtures/golden_round_001.json

    # Locally (won't actually call APIs but demonstrates the dry path):
    python -m tests.parity.record_round --dry-run

The replay test (``test_round_replay.py``) reads this JSON, mocks fetchers
and LLM with the recorded responses, runs ``execute_round``, and asserts the
final paper_ids / scores match the recorded ``expected_output``.

Run again with ``--update`` to refresh the fixture after intentional
behaviour changes (analogous to phase-level ``--update-golden``).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, cast

logger = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-id", help="UUID of project to run a round on.")
    p.add_argument(
        "--output", required=False, type=Path,
        help="Where to write the fixture JSON.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without touching DB / network.",
    )
    return p.parse_args(argv[1:])


async def record(project_id: str, output: Path) -> dict:
    """Run a real round, capturing fetcher + LLM IO. Returns the fixture dict."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession, async_sessionmaker, create_async_engine,
    )

    from app.config import settings
    from app.services.core.llm_config_store import get_llm_manager
    from app.services.fetchers.international import ALL_FETCHERS
    from app.workers.search_tasks import _execute_round_async
    from tests.parity.recorder import FetcherRecorder, LLMRecorder

    engine = create_async_engine(settings.database_url, echo=False)
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    llm_manager = await get_llm_manager()

    # Mapping is key-invariant; ALL_FETCHERS uses Literal keys, recorder
    # accepts Mapping[str, Any]. Bridge with cast — covariance is fine
    # because the recorder only reads keys as labels, never narrows them.
    fetcher_capture = FetcherRecorder(cast(Mapping[str, Any], ALL_FETCHERS))
    llm_capture = LLMRecorder({"main": llm_manager})

    with fetcher_capture, llm_capture:
        result = await _execute_round_async(project_id)

    # Pull the final ranking out of the DB so the replay can assert on it.
    expected = await _snapshot_round_output(project_id, sessionmaker)
    await engine.dispose()

    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "input": {"project_id": project_id},
        "fetcher_captures": fetcher_capture.captures,
        "llm_captures": llm_capture.captures,
        "round_result": result,
        "expected_output": expected,
    }


async def _snapshot_round_output(project_id: str, sessionmaker) -> dict:
    """Produce a stable summary of what the round ended up writing — used as
    the assertion target in the replay test."""
    import uuid

    from sqlalchemy import select

    from app.models.document import Document
    from app.models.round_document import RoundDocument
    from app.models.search_round import SearchRound

    pid = uuid.UUID(project_id)
    async with sessionmaker() as db:
        rounds = await db.execute(
            select(SearchRound)
            .where(SearchRound.project_id == pid)
            .order_by(SearchRound.created_at.desc())
            .limit(1)
        )
        latest = rounds.scalar_one_or_none()
        if not latest:
            return {"error": "no rounds for project"}

        docs_q = await db.execute(
            select(Document.source, Document.external_id, RoundDocument.agent_score)
            .join(RoundDocument, RoundDocument.document_id == Document.id)
            .where(RoundDocument.round_id == latest.id)
            .order_by(RoundDocument.agent_score.desc().nullslast())
        )
        paper_ids = []
        scores: dict[str, float] = {}
        for source, ext_id, agent_score in docs_q.all():
            key = f"{source}:{ext_id}"
            paper_ids.append(key)
            if agent_score is not None:
                scores[key] = float(agent_score)
        return {
            "round_id": str(latest.id),
            "paper_ids": paper_ids,
            "scores": scores,
            "total_count": len(paper_ids),
        }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.dry_run:
        print("[record_round] dry-run: would record project="
              f"{args.project_id} → {args.output}")
        return 0

    if not args.project_id or not args.output:
        print("error: --project-id and --output are required (or --dry-run)",
              file=sys.stderr)
        return 2

    fixture = asyncio.run(record(args.project_id, args.output))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"[record_round] wrote {len(fixture['fetcher_captures'])} fetcher + "
        f"{len(fixture['llm_captures'])} LLM captures to {args.output}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
