"""Admin routes 鉴权：无 token → 401。"""
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def test_admin_invitations_needs_auth():
    c = _client()
    r = c.get("/api/admin/invitations")
    assert r.status_code == 401, f"unexpected: {r.status_code}"


def test_admin_users_list_needs_auth():
    c = _client()
    r = c.get("/api/admin/users")
    assert r.status_code == 401


def test_admin_users_stats_needs_auth():
    c = _client()
    r = c.get("/api/admin/users/stats")
    assert r.status_code == 401


def test_fetcher_search_needs_auth():
    c = _client()
    r = c.post("/api/fetcher/search", json={"source": "openalex", "keywords": "x"})
    assert r.status_code == 401


def test_client_meta_old_desktop_blocked():
    """desktop 客户端版本太低应该返 426 Upgrade Required。"""
    c = _client()
    r = c.get(
        "/api/admin/users",
        headers={"X-Client-Type": "desktop", "X-Client-Version": "0.0.1"},
    )
    assert r.status_code == 426, f"expected 426 Upgrade Required, got {r.status_code}"
    body = r.json()
    assert body.get("code") == "client_upgrade_required"


def test_client_meta_no_version_blocked_for_desktop():
    """desktop 客户端不带 X-Client-Version 也 426。"""
    c = _client()
    r = c.get(
        "/api/admin/users",
        headers={"X-Client-Type": "desktop"},
    )
    assert r.status_code == 426


def test_client_meta_web_passes():
    """web 客户端不受版本拦截。"""
    c = _client()
    r = c.get("/api/admin/users", headers={"X-Client-Type": "web"})
    # 401 = 走到了鉴权层（未拦截）；不是 426
    assert r.status_code != 426
