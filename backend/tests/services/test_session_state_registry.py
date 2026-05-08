import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from app.services.session_state_registry import (
    REGISTRY, exitable_states, get,
)

pytestmark = pytest.mark.asyncio


def test_all_expected_states_registered():
    expected = {
        "idle", "intent_analysis", "intent_confirmation",
        "search_mode_selection", "keyword_confirmation",
        "searching", "scoring", "classification", "round_finalize",
        "collaboration_selecting", "collaboration_active",
    }
    assert expected.issubset(set(REGISTRY.keys())), f"missing: {expected - set(REGISTRY.keys())}"


def test_task_states_not_exitable():
    for state in ("searching", "scoring"):
        assert REGISTRY[state].exitable is False


def test_dialog_states_exitable():
    for state in (
        "intent_confirmation", "search_mode_selection", "keyword_confirmation",
        "collaboration_selecting", "collaboration_active",
    ):
        assert REGISTRY[state].exitable is True


def test_idle_not_exitable():
    assert REGISTRY["idle"].exitable is False


def test_exitable_states_helper():
    exitable = exitable_states()
    assert "intent_confirmation" in exitable
    assert "searching" not in exitable
    assert "idle" not in exitable


def test_get_unknown_state_returns_non_exitable():
    """Unknown state should log warning and return non-exitable spec (fail-safe)."""
    spec = get("made_up_state")
    assert spec.exitable is False


async def test_exit_keyword_clears_redis_and_cancels_round():
    from app.services.session_state_registry import _exit_keyword
    from datetime import datetime, timezone

    round_id = uuid.uuid4()
    session = MagicMock()
    session.state_data = {"current_round_id": str(round_id)}
    db = AsyncMock()
    redis = AsyncMock()
    round_obj = MagicMock(status="keyword_confirmation")
    db.get = AsyncMock(return_value=round_obj)

    await _exit_keyword(session, db, redis)

    redis.delete.assert_awaited_once()
    delete_args = redis.delete.await_args.args
    assert "keyword_plan" in delete_args[0]
    assert round_obj.status == "cancelled"
    assert round_obj.cancelled_reason == "user_exit_keyword_confirmation"
    assert round_obj.cancelled_at is not None


async def test_exit_intent_clears_project_draft():
    from app.services.session_state_registry import _exit_intent

    session = MagicMock()
    session.state_data = {"project_draft": {"name": "tentative"}}
    db = AsyncMock()
    redis = AsyncMock()

    await _exit_intent(session, db, redis)

    assert "project_draft" not in session.state_data
