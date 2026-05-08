"""Smoke tests verifying the integration-test fixture chain works end-to-end."""


async def test_fresh_project_in_fresh_scene(fresh_project):
    assert fresh_project.current_round == 0


async def test_async_client_health(async_client):
    """Verify async_client can reach the app (public endpoint, no auth needed)."""
    resp = await async_client.get("/health")
    assert resp.status_code == 200


async def test_async_client_auth_override(async_client, test_user):
    """
    Verify auth_headers work when get_current_user is overridden.
    async_client has its own DB sessions; auth is overridden so the user
    doesn't need to be visible in a separate connection.
    """
    from app.main import app
    from app.dependencies import get_current_user

    # Override get_current_user to return our in-savepoint test_user
    app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        resp = await async_client.get("/api/projects/")
        assert resp.status_code in (200, 307, 404)
    finally:
        # Remove only this override; async_client manages get_db override itself
        app.dependency_overrides.pop(get_current_user, None)


async def test_session_with_active_round_factory(session_with_active_round):
    session, round_ = await session_with_active_round("keyword_confirmation")
    assert session.current_state == "keyword_confirmation"
    assert session.state_data["current_round_id"] == str(round_.id)
