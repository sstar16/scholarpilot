"""Verify natural-language intent -> FeatureGate integration.

When the IntentRouter classifies a message as "analyze_documents" but the
project is in FRESH scene (current_round=0), the gate must block and emit a
feature_gate_blocked rich message -- without entering collaboration_selecting.
"""
import pytest
import uuid
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.asyncio


def _override_auth(user):
    from app.main import app
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_auth():
    from app.main import app
    from app.dependencies import get_current_user
    app.dependency_overrides.pop(get_current_user, None)


async def _make_fresh_project_and_session(db, user_id):
    """Create project (current_round=0 = FRESH) + conversation session, both committed."""
    from app.models.project import Project
    from app.models.conversation_session import ConversationSession

    project = Project(
        user_id=user_id,
        title="gate-intent-test-" + uuid.uuid4().hex[:6],
        description="",
        domain="computer_science",
        current_round=0,  # FRESH scene -- collaboration blocked
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    sess = ConversationSession(
        user_id=user_id,
        project_id=project.id,
        current_state="classification",
        state_data={},
        messages=[],
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return project, sess


async def test_analyze_documents_intent_in_fresh_scene_returns_gate_blocked(
    async_client, test_user, db
):
    """If user sends a collaboration intent in FRESH scene, gate should block
    and emit a feature_gate_blocked rich payload -- NOT enter collaboration."""
    _project, sess = await _make_fresh_project_and_session(db, test_user.id)
    _override_auth(test_user)
    try:
        # Patch _run_intent_router so no real LLM call happens
        with patch(
            "app.api.conversation._run_intent_router",
            new=AsyncMock(return_value={"intent": "analyze_documents", "extracted": {}}),
        ):
            resp = await async_client.post(
                f"/api/conversation/{sess.id}/message",
                json={"content": "analyze docs please"},
            )
    finally:
        _clear_auth()

    assert resp.status_code == 200
    body = resp.json()
    # Must NOT transition to collaboration_selecting
    assert body["state"] != "collaboration_selecting"
    # Response must mention the block (gate reason contains these characters)
    assert "\u65e0\u6cd5" in body["content"]  # "无法"
    assert "\u534f\u4f5c\u6a21\u5f0f" in body["content"]  # "协作模式"
