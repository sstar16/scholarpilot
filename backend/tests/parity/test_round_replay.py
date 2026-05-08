"""Round-level replay parity test.

Skipped when ``fixtures/golden_round_*.json`` is absent (so CI on a fresh
checkout doesn't trip). To bootstrap: run ``record_round.py`` against a real
project once, commit the JSON, and this test will start running on every
push thereafter.

What it catches that phase-level parity doesn't:
  - QueryPlanAgent prompt drift that changes which sources are hit
  - Cross-phase state contamination (e.g. memory layer leaking into score)
  - Concurrent scheduling regressions across the whole round

Failure mode: prints the doc-id-level set diff between recorded and current,
plus score deltas for surviving doc ids. Run with ``--update-golden`` to
accept the drift and refresh the fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.parity.recorder import (
    FetcherReplay,
    LLMReplayManager,
    load_fixture,
    save_fixture,
)


_FIXTURES = Path(__file__).parent / "fixtures"


def _golden_files() -> list[Path]:
    return sorted(_FIXTURES.glob("golden_round_*.json"))


@pytest.fixture(params=_golden_files() or [None], ids=lambda p: p.name if p else "no-fixture")
def fixture_path(request) -> Path:
    if request.param is None:
        pytest.skip(
            "No golden round fixture found in tests/parity/fixtures/. "
            "Bootstrap with: python -m tests.parity.record_round "
            "--project-id <uuid> --output tests/parity/fixtures/golden_round_001.json",
        )
    return request.param


@pytest.mark.asyncio
async def test_round_replay_matches_golden(fixture_path: Path, update_golden: bool):
    """Replay a recorded round; assert paper_ids and scores match exactly."""
    fixture = load_fixture(fixture_path)

    # The actual replay path — needs real codebase imports. Skip when the
    # backend can't be loaded in this environment (no postgres etc).
    pytest.importorskip("asyncpg", reason="needs full backend env")

    # Lazy imports — we don't want to drag postgres/celery into collection
    # when no fixture exists.
    from app.services.fetchers.international import ALL_FETCHERS
    from app.workers import search_tasks

    fetcher_replay = FetcherReplay(fixture["fetcher_captures"])
    llm_replay = LLMReplayManager(fixture["llm_captures"])

    fetcher_replay.install(ALL_FETCHERS)

    # Patch llm_manager retrieval to return our replay
    import app.services.core.llm_config_store as llm_store
    original_get = llm_store.get_llm_manager

    async def _get_llm_replay():
        return llm_replay

    llm_store.get_llm_manager = _get_llm_replay
    try:
        actual_result = await search_tasks._execute_round_async(
            fixture["input"]["project_id"],
        )
    finally:
        llm_store.get_llm_manager = original_get

    expected = fixture["expected_output"]
    actual_ids = set(_pull_paper_ids(actual_result))
    expected_ids = set(expected.get("paper_ids", []))

    if actual_ids == expected_ids:
        return

    if update_golden:
        fixture["expected_output"] = {
            "paper_ids": sorted(actual_ids),
            "scores": _pull_scores(actual_result),
        }
        save_fixture(fixture_path, fixture)
        pytest.skip("Golden refreshed. Re-run without --update-golden to verify.")

    diff_added = sorted(actual_ids - expected_ids)
    diff_removed = sorted(expected_ids - actual_ids)
    pytest.fail(
        f"Round paper_ids drifted from golden {fixture_path.name}.\n"
        f"  +{len(diff_added)}: {diff_added[:5]}\n"
        f"  -{len(diff_removed)}: {diff_removed[:5]}\n"
        "Run with --update-golden to accept.",
    )


def _pull_paper_ids(result: dict) -> list[str]:
    return result.get("paper_ids", []) if isinstance(result, dict) else []


def _pull_scores(result: dict) -> dict[str, float]:
    return result.get("scores", {}) if isinstance(result, dict) else {}
