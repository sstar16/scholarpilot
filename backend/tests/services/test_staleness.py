"""Tests for app/services/staleness.py — pure logic, mocked DB."""
from __future__ import annotations

import sys
import types
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Stub heavy modules before importing staleness, mirroring test_pipeline_runner.
_inject_stub = types.ModuleType("app.services.conversation_inject")
_inject_stub.inject_rich_message = AsyncMock(return_value=True)
sys.modules.setdefault("app.services.conversation_inject", _inject_stub)

# Avoid pulling event_bus/redis at import time.
_event_stub = types.ModuleType("app.services.event_bus")
_event_stub.EventBus = MagicMock()
sys.modules.setdefault("app.services.event_bus", _event_stub)

from app.services.staleness import (  # noqa: E402
    StaleStatus,
    check_and_inject_stale_hint,
    dismiss_stale_hint,
)


# ── Fakes ───────────────────────────────────────────────────────────────────


@dataclass
class _FakeRound:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    completed_at: Any = None


@dataclass
class _FakeSession:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    messages: list = field(default_factory=list)
    state_data: dict = field(default_factory=dict)


class _FakeDB:
    """Stub for AsyncSession that routes by which model the SELECT targets.
    Inspecting str(stmt) is fragile to SQL dialect changes but plenty robust
    for these three-line queries."""

    def __init__(
        self,
        round_: _FakeRound | None = None,
        session: _FakeSession | None = None,
    ):
        self._round = round_
        self._session = session
        self.commit = AsyncMock()

    async def execute(self, stmt):
        sql = str(stmt).lower()
        result = MagicMock()
        if "search_round" in sql:
            result.scalar_one_or_none = MagicMock(return_value=self._round)
        elif "conversation_session" in sql:
            result.scalar_one_or_none = MagicMock(return_value=self._session)
        else:
            result.scalar_one_or_none = MagicMock(return_value=None)
        return result


def _now() -> datetime:
    return datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)


def _stub_inject(monkeypatch, *, return_value=True):
    """Reset the inject stub for a test, return the mock for inspection."""
    mock = AsyncMock(return_value=return_value)
    monkeypatch.setattr(
        sys.modules["app.services.conversation_inject"],
        "inject_rich_message",
        mock,
    )
    # Also rebind the symbol the staleness module imported at load time.
    import app.services.staleness as st
    monkeypatch.setattr(st, "inject_rich_message", mock)
    return mock


@pytest.fixture(autouse=True)
def _patch_flag_modified(monkeypatch):
    """SQLAlchemy's flag_modified expects a real ORM instance; tests use
    dataclass fakes, so make it a no-op."""
    import app.services.staleness as st
    monkeypatch.setattr(st, "flag_modified", lambda *_a, **_kw: None)


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_completed_rounds_is_not_stale(monkeypatch):
    """No completed round at all → not stale, days_ago=None."""
    inject = _stub_inject(monkeypatch)
    db = _FakeDB(round_=None)
    pid = uuid.uuid4()
    status = await check_and_inject_stale_hint(pid, db, now=_now())
    assert isinstance(status, StaleStatus)
    assert status.is_stale is False
    assert status.days_ago is None
    inject.assert_not_called()


@pytest.mark.asyncio
async def test_recent_round_is_not_stale(monkeypatch):
    """Last round 3 days ago, threshold 7 → not stale."""
    inject = _stub_inject(monkeypatch)
    db = _FakeDB(round_=_FakeRound(completed_at=_now() - timedelta(days=3)))
    status = await check_and_inject_stale_hint(uuid.uuid4(), db, now=_now())
    assert status.is_stale is False
    assert status.days_ago == 3
    inject.assert_not_called()


@pytest.mark.asyncio
async def test_stale_no_session_still_returns_stale(monkeypatch):
    """Past threshold + no active session → still flagged stale; we just
    can't inject anywhere, so the inject helper returns False."""
    inject = _stub_inject(monkeypatch, return_value=False)
    db = _FakeDB(
        round_=_FakeRound(completed_at=_now() - timedelta(days=10)),
        session=None,
    )
    status = await check_and_inject_stale_hint(uuid.uuid4(), db, now=_now())
    assert status.is_stale is True
    assert status.days_ago == 10
    inject.assert_awaited_once()
    assert status.just_injected is False


@pytest.mark.asyncio
async def test_stale_with_session_injects(monkeypatch):
    inject = _stub_inject(monkeypatch, return_value=True)
    db = _FakeDB(
        round_=_FakeRound(completed_at=_now() - timedelta(days=14)),
        session=_FakeSession(messages=[], state_data={}),
    )
    status = await check_and_inject_stale_hint(uuid.uuid4(), db, now=_now())
    assert status.is_stale is True
    assert status.days_ago == 14
    assert status.just_injected is True
    inject.assert_awaited_once()
    kwargs = inject.await_args.kwargs
    assert kwargs["rich_type"] == "stale_hint"
    assert kwargs["rich_data"]["days_ago"] == 14


@pytest.mark.asyncio
async def test_dedup_within_window_skips_inject(monkeypatch):
    """Same session already has a stale_hint 6h ago, dedup window 24h → no re-inject."""
    inject = _stub_inject(monkeypatch)
    six_hours_ago = (_now() - timedelta(hours=6)).isoformat()
    db = _FakeDB(
        round_=_FakeRound(completed_at=_now() - timedelta(days=10)),
        session=_FakeSession(messages=[
            {"rich_type": "stale_hint", "timestamp": six_hours_ago},
        ]),
    )
    status = await check_and_inject_stale_hint(uuid.uuid4(), db, now=_now())
    assert status.is_stale is True  # still stale, just don't repeat the bubble
    inject.assert_not_called()
    assert status.just_injected is False


@pytest.mark.asyncio
async def test_dedup_old_hint_outside_window_re_injects(monkeypatch):
    """Last hint 30h ago, dedup window 24h → re-inject."""
    inject = _stub_inject(monkeypatch, return_value=True)
    thirty_hours_ago = (_now() - timedelta(hours=30)).isoformat()
    db = _FakeDB(
        round_=_FakeRound(completed_at=_now() - timedelta(days=10)),
        session=_FakeSession(messages=[
            {"rich_type": "stale_hint", "timestamp": thirty_hours_ago},
        ]),
    )
    await check_and_inject_stale_hint(uuid.uuid4(), db, now=_now())
    inject.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismissed_window_suppresses(monkeypatch):
    """User dismissed yesterday for a week → no inject, is_stale=False."""
    inject = _stub_inject(monkeypatch)
    until = (_now() + timedelta(days=5)).isoformat()
    db = _FakeDB(
        round_=_FakeRound(completed_at=_now() - timedelta(days=10)),
        session=_FakeSession(state_data={"stale_hint_dismissed_until": until}),
    )
    status = await check_and_inject_stale_hint(uuid.uuid4(), db, now=_now())
    assert status.is_stale is False
    assert status.suppressed_until is not None
    inject.assert_not_called()


@pytest.mark.asyncio
async def test_dismiss_endpoint_sets_state(monkeypatch):
    db = _FakeDB(session=_FakeSession())
    status = await dismiss_stale_hint(uuid.uuid4(), db, now=_now(), days=7)
    assert status.suppressed_until is not None
    expected = _now() + timedelta(days=7)
    assert abs((status.suppressed_until - expected).total_seconds()) < 1
    db.commit.assert_awaited()
    assert "stale_hint_dismissed_until" in db._session.state_data


@pytest.mark.asyncio
async def test_dismiss_no_session_is_no_op(monkeypatch):
    db = _FakeDB(session=None)
    status = await dismiss_stale_hint(uuid.uuid4(), db, now=_now())
    assert status.suppressed_until is None
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_threshold_boundary_inclusive(monkeypatch):
    """days_ago == threshold should already be considered stale (>=)."""
    inject = _stub_inject(monkeypatch, return_value=True)
    db = _FakeDB(
        round_=_FakeRound(completed_at=_now() - timedelta(days=7)),
        session=_FakeSession(),
    )
    status = await check_and_inject_stale_hint(
        uuid.uuid4(), db, now=_now(), threshold_days=7,
    )
    assert status.is_stale is True
    assert status.days_ago == 7


@pytest.mark.asyncio
async def test_completed_at_naive_is_treated_as_utc(monkeypatch):
    """Some legacy rows may have naive datetimes; service must not crash."""
    inject = _stub_inject(monkeypatch, return_value=True)
    naive = (_now() - timedelta(days=10)).replace(tzinfo=None)
    db = _FakeDB(
        round_=_FakeRound(completed_at=naive),
        session=_FakeSession(),
    )
    status = await check_and_inject_stale_hint(uuid.uuid4(), db, now=_now())
    assert status.is_stale is True
    assert status.days_ago == 10
