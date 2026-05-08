"""ScorePhase golden-fixture parity test.

Catches:
  - ScoringAgent prompt/parser changes that move scores
  - cutoff arithmetic regressions
  - sort/dedup logic regressions
  - changes in concurrent scheduling that surface as wrong-doc-gets-wrong-score

Run with ``--update-golden`` to refresh ``fixtures/score_phase_v1.json`` after
an intentional behaviour change. Without the flag, drift fails the test with
a diff that pinpoints which doc-id changed score / bucket.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Stub heavy modules ScorePhase will lazy-import inside execute(). All these
# need to be in sys.modules BEFORE the first call so the lazy import picks up
# the stubs instead of dragging redis/asyncpg into the parity test.
for modname, attrs in [
    ("app.services.partial_synthesizer", {
        "is_interrupt_requested": AsyncMock(return_value=False),
        "synthesize_partial": AsyncMock(),
        "clear_interrupt_flag": AsyncMock(),
    }),
    ("app.services.answer_now_helpers", {
        "deliver_partial_answer": AsyncMock(),
    }),
    ("app.services.event_bus", {
        "EventBus": MagicMock(publish_sync=MagicMock()),
    }),
]:
    m = types.ModuleType(modname)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules.setdefault(modname, m)


from app.harness.pipeline import RoundContext  # noqa: E402
from app.harness.pipeline.phases.score import ScorePhase  # noqa: E402
from tests.parity.recorder import (  # noqa: E402
    LLMReplay,
    StubLLMManager,
    load_fixture,
    save_fixture,
)


# ── Content-aware LLM replay (order-insensitive) ──────────────────────────


class _ContentMatchedLLM:
    """Returns the response whose title-substring key appears in the prompt.

    ScoringAgent's ``score_all`` runs ``asyncio.gather`` over docs which makes
    the call order non-deterministic; matching by content keeps the test stable
    regardless of which task happened to win the scheduler that run."""

    def __init__(self, by_title: dict[str, str]):
        self._by_title = by_title
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, **_kwargs):
        for needle, response in self._by_title.items():
            if needle in prompt:
                self.calls.append((needle, response))
                return response
        raise RuntimeError(
            f"No fixture response matched prompt; first 200 chars: "
            f"{prompt[:200]!r}\n"
            f"Configured needles: {list(self._by_title.keys())}"
        )


# ── Helpers ────────────────────────────────────────────────────────────────


def _build_ctx(fixture: dict, llm) -> RoundContext:
    inp = fixture["input"]
    project = MagicMock()
    project.title = inp["project"]["title"]
    project.description = inp["project"]["description"]
    project.search_config = {}

    ctx = RoundContext(
        round_id="round-parity",
        db=MagicMock(),
        redis=MagicMock(),
        llm_manager=llm,
    )
    ctx.project = project
    ctx.artifacts["rerank"] = {
        "selected_docs": [dict(d) for d in inp["docs"]],
        "reranked": False,
    }
    ctx.artifacts["load_round"] = {
        "scoring_cutoff": inp["scoring_cutoff"],
    }
    ctx.artifacts["load_memory"] = {
        "combined_md": inp["memory_md"],
    }
    return ctx


def _summarise_output(out: dict) -> dict:
    """Reduce ScorePhase output to a stable, comparable shape."""
    above_ids = sorted(d["external_id"] for d in out["above_cutoff"])
    below_ids = sorted(d["external_id"] for d in out["below_cutoff"])
    scores = {d["external_id"]: d["_agent_score"] for d in out["selected_docs"]}
    return {
        "above_cutoff_ids": above_ids,
        "below_cutoff_ids": below_ids,
        "scores": scores,
        "above_cutoff_count": len(out["above_cutoff"]),
        "below_cutoff_count": len(out["below_cutoff"]),
        "cutoff": out["cutoff"],
    }


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _silence_event_bus():
    """The sys.modules stub above already routes EventBus to a MagicMock —
    just refresh publish_sync's call count for each test."""
    ev = sys.modules["app.services.event_bus"]
    ev.EventBus.publish_sync = MagicMock()


@pytest.mark.asyncio
async def test_score_phase_matches_golden(fixtures_dir, update_golden):
    fixture_path = fixtures_dir / "score_phase_v1.json"
    fixture = load_fixture(fixture_path)
    llm = _ContentMatchedLLM(fixture["llm_responses_by_title_substring"])

    ctx = _build_ctx(fixture, llm)
    out = await ScorePhase().execute(ctx)
    actual = _summarise_output(out)
    expected = fixture["expected_output"]

    if actual == expected:
        return

    # Drift detected — either accept (--update-golden) or fail with diff.
    if update_golden:
        fixture["expected_output"] = actual
        save_fixture(fixture_path, fixture)
        pytest.skip(
            "Golden updated. Re-run without --update-golden to verify."
        )

    diff = _diff(actual, expected)
    pytest.fail(
        "ScorePhase output drifted from golden.\n"
        "Run with: pytest tests/parity/ --update-golden  to accept.\n"
        f"\n{diff}"
    )


@pytest.mark.asyncio
async def test_score_phase_idempotent_within_run(fixtures_dir):
    """Same input + same LLM responses → identical output across two runs.
    This catches non-determinism that's invisible to the golden test if the
    golden happened to be regenerated together with the bug."""
    fixture = load_fixture(fixtures_dir / "score_phase_v1.json")

    async def _run() -> dict:
        llm = _ContentMatchedLLM(fixture["llm_responses_by_title_substring"])
        out = await ScorePhase().execute(_build_ctx(fixture, llm))
        return _summarise_output(out)

    a = await _run()
    b = await _run()
    assert a == b, f"Non-deterministic output:\n a={a}\n b={b}"


@pytest.mark.asyncio
async def test_score_phase_skips_when_no_docs():
    """Empty rerank output → PhaseSkipped, no LLM call."""
    from app.harness.pipeline import PhaseSkipped

    llm = _ContentMatchedLLM({})
    ctx = RoundContext(
        round_id="r", db=MagicMock(), redis=MagicMock(), llm_manager=llm,
    )
    ctx.project = MagicMock(title="t", description="d", search_config={})
    ctx.artifacts["rerank"] = {"selected_docs": [], "reranked": False}
    ctx.artifacts["load_round"] = {"scoring_cutoff": 7.0}
    ctx.artifacts["load_memory"] = {"combined_md": ""}
    with pytest.raises(PhaseSkipped):
        await ScorePhase().execute(ctx)
    assert llm.calls == []


# ── diff helper ────────────────────────────────────────────────────────────


def _diff(actual: dict, expected: dict) -> str:
    lines = []
    keys = set(actual) | set(expected)
    for k in sorted(keys):
        a = actual.get(k)
        e = expected.get(k)
        if a == e:
            continue
        lines.append(f"  {k}:")
        lines.append(f"    expected = {e!r}")
        lines.append(f"    actual   = {a!r}")
        if k == "scores" and isinstance(a, dict) and isinstance(e, dict):
            for did in sorted(set(a) | set(e)):
                if a.get(did) != e.get(did):
                    lines.append(
                        f"      {did}: {e.get(did)!r} → {a.get(did)!r}"
                    )
    return "\n".join(lines) if lines else "(no differences)"
