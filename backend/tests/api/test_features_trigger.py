"""Integration tests for /api/projects/{project_id}/features endpoints."""
import pytest
import uuid
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _override_auth(user):
    from app.main import app
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_auth():
    from app.main import app
    from app.dependencies import get_current_user
    app.dependency_overrides.pop(get_current_user, None)


async def _make_committed_project(db, user_id, current_round=0):
    """Create + commit a project so async_client's independent session sees it."""
    from app.models.project import Project
    p = Project(
        user_id=user_id,
        title=f"featuregate-test-{uuid.uuid4().hex[:6]}",
        description="",
        domain="computer_science",
        current_round=current_round,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def test_check_all_returns_4_features_for_fresh_project(async_client, test_user, db):
    project = await _make_committed_project(db, test_user.id, current_round=0)
    _override_auth(test_user)
    try:
        resp = await async_client.get(f"/api/projects/{project.id}/features/check-all")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"new_round", "collaboration", "schedule", "pdf_import"}
        assert body["new_round"]["allowed"] is True
        assert body["collaboration"]["allowed"] is False
        assert body["collaboration"]["reason"]
        assert body["pdf_import"]["allowed"] is True
    finally:
        _clear_auth()


async def test_trigger_blocked_returns_rich_message(async_client, test_user, db):
    project = await _make_committed_project(db, test_user.id, current_round=0)
    _override_auth(test_user)
    try:
        resp = await async_client.post(
            f"/api/projects/{project.id}/features/trigger",
            json={"feature": "collaboration", "session_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["allowed"] is False
        assert body["rich_message"]["rich_type"] == "feature_gate_blocked"
        assert body["rich_message"]["feature"] == "collaboration"
        assert body["rich_message"]["suggested_action"]
    finally:
        _clear_auth()


async def test_trigger_allowed_pdf_import_in_fresh(async_client, test_user, db):
    project = await _make_committed_project(db, test_user.id, current_round=0)
    _override_auth(test_user)
    try:
        resp = await async_client.post(
            f"/api/projects/{project.id}/features/trigger",
            json={"feature": "pdf_import", "session_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["allowed"] is True
        assert body["rich_message"]["rich_type"] == "feature_gate_allowed"
    finally:
        _clear_auth()


async def test_trigger_unknown_feature_returns_400(async_client, test_user, db):
    project = await _make_committed_project(db, test_user.id, current_round=0)
    _override_auth(test_user)
    try:
        resp = await async_client.post(
            f"/api/projects/{project.id}/features/trigger",
            json={"feature": "bogus", "session_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 400
    finally:
        _clear_auth()
