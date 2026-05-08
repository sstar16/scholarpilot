"""Tests for scripts/analyze_telemetry.py — pure aggregation logic."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to path so we can import analyze_telemetry by name.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))

import analyze_telemetry as at  # noqa: E402


def _make_record(event: str, *, ts: str, user: str = "u1",
                 project: str = "p1") -> dict:
    return {
        "ts": ts, "event": event, "user_id": user, "project_id": project,
    }


def test_ctr_with_one_user_who_clicked():
    records = [
        _make_record("stale_hint_impression", ts="2026-04-27T10:00:00Z"),
        _make_record("stale_hint_clicked", ts="2026-04-27T10:00:30Z"),
    ]
    stats = at.analyse(records)
    day = stats["2026-04-27"]
    assert day["impr"] == 1
    assert day["click"] == 1
    assert day["ctr"] == 100.0
    assert day["ignore"] == 0


def test_ignore_when_no_action():
    records = [
        _make_record("stale_hint_impression", ts="2026-04-27T10:00:00Z"),
    ]
    stats = at.analyse(records)
    day = stats["2026-04-27"]
    assert day["impr"] == 1
    assert day["click"] == 0
    assert day["dismiss"] == 0
    assert day["ignore"] == 1
    assert day["ignore_rate"] == 100.0


def test_dismiss_counts_separately_from_click():
    records = [
        _make_record("stale_hint_impression", ts="2026-04-27T10:00:00Z", user="u1"),
        _make_record("stale_hint_dismissed", ts="2026-04-27T10:01:00Z", user="u1"),
        _make_record("stale_hint_impression", ts="2026-04-27T11:00:00Z", user="u2"),
        _make_record("stale_hint_clicked", ts="2026-04-27T11:00:10Z", user="u2"),
    ]
    stats = at.analyse(records)
    day = stats["2026-04-27"]
    assert day["impr"] == 2
    assert day["click"] == 1
    assert day["dismiss"] == 1
    assert day["ignore"] == 0


def test_click_after_dismiss_wins():
    """If a user both dismisses and clicks the same day, count as click."""
    records = [
        _make_record("stale_hint_impression", ts="2026-04-27T10:00:00Z"),
        _make_record("stale_hint_dismissed", ts="2026-04-27T10:01:00Z"),
        _make_record("stale_hint_clicked", ts="2026-04-27T10:02:00Z"),
    ]
    stats = at.analyse(records)
    day = stats["2026-04-27"]
    assert day["click"] == 1
    assert day["dismiss"] == 0
    assert day["impr"] == 1
    assert day["ctr"] + day["dismiss_rate"] + day["ignore_rate"] == 100.0


def test_groups_by_day():
    records = [
        _make_record("stale_hint_impression", ts="2026-04-26T23:59:00Z", user="u1"),
        _make_record("stale_hint_impression", ts="2026-04-27T00:00:01Z", user="u2"),
    ]
    stats = at.analyse(records)
    assert "2026-04-26" in stats
    assert "2026-04-27" in stats
    assert stats["2026-04-26"]["impr"] == 1
    assert stats["2026-04-27"]["impr"] == 1


def test_repeated_impressions_same_user_collapse():
    """Same user seeing the same hint multiple times in a day → one impr."""
    records = [
        _make_record("stale_hint_impression", ts="2026-04-27T08:00:00Z"),
        _make_record("stale_hint_impression", ts="2026-04-27T14:00:00Z"),
    ]
    stats = at.analyse(records)
    assert stats["2026-04-27"]["impr"] == 1


def test_render_table_handles_empty():
    assert "no telemetry" in at.render_table({})


def test_iter_records_skips_malformed_lines(tmp_path: Path):
    f = tmp_path / "t.jsonl"
    f.write_text(
        '{"event": "stale_hint_impression", "ts": "2026-04-27T10:00:00Z"}\n'
        'not a json line\n'
        '{"event": "stale_hint_clicked", "ts": "2026-04-27T10:01:00Z"}\n',
        encoding="utf-8",
    )
    records = list(at.iter_records(f))
    assert len(records) == 2
    assert {r["event"] for r in records} == {
        "stale_hint_impression", "stale_hint_clicked",
    }
