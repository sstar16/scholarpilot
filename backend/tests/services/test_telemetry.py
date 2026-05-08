"""Tests for app/services/telemetry.py — emit, jsonl mirror, safe coercion."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import pytest

from app.services import telemetry
from app.services.telemetry import KNOWN_EVENTS, emit


@pytest.fixture(autouse=True)
def _redirect_jsonl(tmp_path, monkeypatch):
    """Point the jsonl mirror at a tmp dir; clear after each test."""
    target = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("TELEMETRY_JSONL_PATH", str(target))
    return target


def test_emit_writes_logger_line(caplog):
    caplog.set_level(logging.INFO, logger="app.services.telemetry")
    emit("stale_hint_impression", days_ago=10, threshold=7)
    matches = [r for r in caplog.records if "[telemetry]" in r.message]
    assert matches, "expected a [telemetry] log line"
    rec = matches[-1].telemetry
    assert rec["event"] == "stale_hint_impression"
    assert rec["days_ago"] == 10
    assert rec["threshold"] == 7
    assert "ts" in rec  # ISO timestamp injected


def test_emit_writes_jsonl_mirror(_redirect_jsonl):
    emit("stale_hint_impression", days_ago=12)
    lines = _redirect_jsonl.read_text("utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "stale_hint_impression"
    assert rec["days_ago"] == 12


def test_emit_appends_multiple_events(_redirect_jsonl):
    emit("stale_hint_impression", days_ago=10)
    emit("stale_hint_dismissed", mute_days=7)
    emit("stale_hint_clicked", days_ago=10)
    lines = _redirect_jsonl.read_text("utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events == [
        "stale_hint_impression",
        "stale_hint_dismissed",
        "stale_hint_clicked",
    ]


def test_emit_coerces_uuid_to_str(_redirect_jsonl):
    pid = uuid.uuid4()
    emit("stale_hint_impression", project_id=pid)
    rec = json.loads(_redirect_jsonl.read_text("utf-8").strip())
    assert rec["project_id"] == str(pid)


def test_unknown_event_warns_but_records(_redirect_jsonl, caplog):
    caplog.set_level(logging.WARNING, logger="app.services.telemetry")
    emit("brand_new_event_not_in_known_list", x=1)
    # Logged a warning but still wrote the event (don't lose telemetry).
    assert any("unknown event" in r.message for r in caplog.records)
    rec = json.loads(_redirect_jsonl.read_text("utf-8").strip())
    assert rec["event"] == "brand_new_event_not_in_known_list"


def test_emit_never_raises(monkeypatch):
    """Even if the jsonl write blows up, emit() must not propagate."""
    def _explode(*_a, **_kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(telemetry, "_append_jsonl", _explode)
    # Should not raise (warning may be logged):
    emit("stale_hint_impression", days_ago=1)


def test_known_events_contains_stale_hint_lifecycle():
    assert "stale_hint_impression" in KNOWN_EVENTS
    assert "stale_hint_dismissed" in KNOWN_EVENTS
    assert "stale_hint_clicked" in KNOWN_EVENTS


def test_safe_handles_nested_structures(_redirect_jsonl):
    emit(
        "stale_hint_impression",
        nested={"ids": [uuid.uuid4(), uuid.uuid4()]},
    )
    rec = json.loads(_redirect_jsonl.read_text("utf-8").strip())
    assert isinstance(rec["nested"]["ids"], list)
    assert all(isinstance(s, str) for s in rec["nested"]["ids"])
