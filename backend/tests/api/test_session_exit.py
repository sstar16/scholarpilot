"""Integration tests for POST /api/conversation/sessions/{sid}/exit."""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.conversation_session import ConversationSession
from app.models.search_round import SearchRound

from tests.conftest import _TEST_DB_URL

pytestmark = pytest.mark.asyncio


async def _verify_query(stmt):
    """Run a read-only SELECT using a brand-new engine + session.
    Required because the `db` fixture's session can't safely re-query rows
    that were modified by the endpoint's independent session (asyncpg + NullPool
    cross-session protocol state issues)."""
    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as sess:
            result = await sess.execute(stmt)
            return result.scalar_one()
    finally:
        await engine.dispose()


def _override_auth(user):
    from app.main import app
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_overrides():
    from app.main import app
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _commit_session(db, session_obj):
    """Flush + commit a session so the async_client's independent DB session sees it."""
    await db.commit()
    await db.refresh(session_obj)
    return session_obj


async def _commit_session_and_round(db, sess, round_):
    await db.commit()
    await db.refresh(sess)
    await db.refresh(round_)
    return sess, round_


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_exit_from_idle_rejected(async_client, test_user, db, session_in_state):
    """idle is not exitable — expect 409 NOT_EXITABLE."""
    sess = await session_in_state("idle")
    await _commit_session(db, sess)

    _override_auth(test_user)
    try:
        resp = await async_client.post(f"/api/conversation/sessions/{sess.id}/exit")
        assert resp.status_code == 409
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("code") == "NOT_EXITABLE"
    finally:
        _clear_overrides()


async def test_exit_from_searching_rejected(async_client, test_user, db, session_in_state, fresh_project):
    """searching is not exitable — expect 409."""
    sess = await session_in_state("searching", project=fresh_project)
    await _commit_session(db, sess)

    _override_auth(test_user)
    try:
        resp = await async_client.post(f"/api/conversation/sessions/{sess.id}/exit")
        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"]["code"] == "NOT_EXITABLE"
    finally:
        _clear_overrides()


async def test_exit_from_keyword_confirmation_succeeds_and_cancels_round(
    async_client, test_user, db, session_with_active_round, monkeypatch
):
    """keyword_confirmation exit: 200, round.status='cancelled', session.state='idle'."""
    sess, round_ = await session_with_active_round("keyword_confirmation")
    # Patch the round to keyword_confirmation status so on_exit logic fires
    round_.status = "keyword_confirmation"
    await _commit_session_and_round(db, sess, round_)

    _override_auth(test_user)
    # Patch redis so no real Redis connection needed
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.aclose = AsyncMock()

    with patch("app.api.session_exit.aioredis.from_url", return_value=mock_redis):
        try:
            resp = await async_client.post(f"/api/conversation/sessions/{sess.id}/exit")
        finally:
            _clear_overrides()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["rich_message"]["rich_type"] == "flow_exited"
    assert body["rich_message"]["from_state"] == "keyword_confirmation"

    s_fresh = await _verify_query(
        select(ConversationSession).where(ConversationSession.id == sess.id)
    )
    assert s_fresh.current_state == "idle"

    r_fresh = await _verify_query(
        select(SearchRound).where(SearchRound.id == round_.id)
    )
    assert r_fresh.status == "cancelled"
    assert r_fresh.cancelled_reason == "user_exit_keyword_confirmation"


async def test_exit_from_intent_confirmation_clears_draft(
    async_client, test_user, db, session_in_state
):
    """intent_confirmation exit: 200, project_draft cleared from state_data."""
    sess = await session_in_state(
        "intent_confirmation",
        metadata={"project_draft": {"name": "tentative"}},
    )
    await _commit_session(db, sess)

    _override_auth(test_user)
    try:
        resp = await async_client.post(f"/api/conversation/sessions/{sess.id}/exit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["rich_message"]["from_state"] == "intent_confirmation"
    finally:
        _clear_overrides()

    s_fresh = await _verify_query(
        select(ConversationSession).where(ConversationSession.id == sess.id)
    )
    assert s_fresh.current_state == "idle"
    assert "project_draft" not in (s_fresh.state_data or {})
