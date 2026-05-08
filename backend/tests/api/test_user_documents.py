"""Integration tests for /api/users/me/documents + /api/projects/.../own endpoints.

Spec: docs/spec-pdf-ownership-sync.md
"""
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


async def _make_committed_project(db, user_id):
    from app.models.project import Project
    p = Project(
        user_id=user_id,
        title=f"ownership-test-{uuid.uuid4().hex[:6]}",
        description="",
        domain="computer_science",
        current_round=0,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_committed_document(db):
    from app.models.document import Document
    d = Document(
        source="arxiv",
        external_id=f"ext-{uuid.uuid4().hex[:8]}",
        doc_type="paper",
        title=f"Test Doc {uuid.uuid4().hex[:6]}",
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


# ───────────────────────────────────────────────────────────────────────────


async def test_list_owned_empty(async_client: AsyncClient, test_user, db):
    """新用户 ownership 列表为空。"""
    _override_auth(test_user)
    try:
        resp = await async_client.get("/api/users/me/documents")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"items": []}
    finally:
        _clear_auth()


async def test_own_then_list(async_client: AsyncClient, test_user, db):
    """POST /own 后能在 list 里查到。"""
    project = await _make_committed_project(db, test_user.id)
    doc = await _make_committed_document(db)
    _override_auth(test_user)
    try:
        resp = await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["created"] is True
        assert body["source"] == "downloaded"
        assert body["format"] == "pdf"

        list_resp = await async_client.get("/api/users/me/documents")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["document_id"] == str(doc.id)
        assert items[0]["project_id"] == str(project.id)
        assert items[0]["source"] == "downloaded"
    finally:
        _clear_auth()


async def test_own_idempotent_updates_last_seen(async_client: AsyncClient, test_user, db):
    """同一 (user, doc, project, format) 第二次 own 不创建新记录，只更新 last_seen_at。"""
    project = await _make_committed_project(db, test_user.id)
    doc = await _make_committed_document(db)
    _override_auth(test_user)
    try:
        r1 = await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
        assert r1.json()["created"] is True
        last_seen_1 = r1.json()["last_seen_at"]

        r2 = await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
        assert r2.json()["created"] is False
        last_seen_2 = r2.json()["last_seen_at"]
        # last_seen_at 应当 >= 之前的（同一秒可能相等）
        assert last_seen_2 >= last_seen_1

        # 仍只有 1 条 ownership
        list_resp = await async_client.get("/api/users/me/documents")
        assert len(list_resp.json()["items"]) == 1
    finally:
        _clear_auth()


async def test_own_source_upgrade(async_client: AsyncClient, test_user, db):
    """uploaded_local → downloaded → uploaded_synced 应当升级。
    反向（已 uploaded_synced 后调 uploaded_local）不降级。"""
    project = await _make_committed_project(db, test_user.id)
    doc = await _make_committed_document(db)
    _override_auth(test_user)
    try:
        # 1. 上传本地
        r1 = await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "uploaded_local", "format": "pdf"},
        )
        assert r1.json()["source"] == "uploaded_local"

        # 2. 升级到 downloaded（用户后来从 backend 下了一份覆盖）
        r2 = await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
        assert r2.json()["source"] == "downloaded"

        # 3. 升级到 uploaded_synced（用户主动选了云同步）
        r3 = await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "uploaded_synced", "format": "pdf"},
        )
        assert r3.json()["source"] == "uploaded_synced"

        # 4. 反向不降级
        r4 = await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "uploaded_local", "format": "pdf"},
        )
        assert r4.json()["source"] == "uploaded_synced"  # 保持升级状态
    finally:
        _clear_auth()


async def test_unown_removes(async_client: AsyncClient, test_user, db):
    """DELETE /own 后 list 看不到。"""
    project = await _make_committed_project(db, test_user.id)
    doc = await _make_committed_document(db)
    _override_auth(test_user)
    try:
        await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
        del_resp = await async_client.delete(
            f"/api/projects/{project.id}/documents/{doc.id}/own?format=pdf"
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["removed"] is True

        list_resp = await async_client.get("/api/users/me/documents")
        assert list_resp.json()["items"] == []
    finally:
        _clear_auth()


async def test_unown_idempotent_when_not_exists(async_client: AsyncClient, test_user, db):
    """从未 own 过的 doc 直接 DELETE 仍返 200。"""
    project = await _make_committed_project(db, test_user.id)
    doc = await _make_committed_document(db)
    _override_auth(test_user)
    try:
        del_resp = await async_client.delete(
            f"/api/projects/{project.id}/documents/{doc.id}/own?format=pdf"
        )
        assert del_resp.status_code == 200
    finally:
        _clear_auth()


async def test_list_filter_by_project(async_client: AsyncClient, test_user, db):
    """list ?project_id 只返回指定 project 的 ownership。"""
    p1 = await _make_committed_project(db, test_user.id)
    p2 = await _make_committed_project(db, test_user.id)
    doc1 = await _make_committed_document(db)
    doc2 = await _make_committed_document(db)
    _override_auth(test_user)
    try:
        await async_client.post(
            f"/api/projects/{p1.id}/documents/{doc1.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
        await async_client.post(
            f"/api/projects/{p2.id}/documents/{doc2.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )

        # filter by p1
        r1 = await async_client.get(f"/api/users/me/documents?project_id={p1.id}")
        items_1 = r1.json()["items"]
        assert len(items_1) == 1
        assert items_1[0]["project_id"] == str(p1.id)

        # 全部
        r_all = await async_client.get("/api/users/me/documents")
        assert len(r_all.json()["items"]) == 2
    finally:
        _clear_auth()


async def test_list_filter_by_format(async_client: AsyncClient, test_user, db):
    """list ?format=pdf 只返回 PDF ownership。"""
    project = await _make_committed_project(db, test_user.id)
    doc = await _make_committed_document(db)
    _override_auth(test_user)
    try:
        await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
        await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "html"},
        )

        r_pdf = await async_client.get("/api/users/me/documents?format=pdf")
        assert len(r_pdf.json()["items"]) == 1
        assert r_pdf.json()["items"][0]["format"] == "pdf"

        r_html = await async_client.get("/api/users/me/documents?format=html")
        assert len(r_html.json()["items"]) == 1
        assert r_html.json()["items"][0]["format"] == "html"

        r_all = await async_client.get("/api/users/me/documents")
        assert len(r_all.json()["items"]) == 2
    finally:
        _clear_auth()


async def test_isolation_other_users_cannot_see(async_client: AsyncClient, test_user, db):
    """另一个 user 的 ownership 对当前 user 不可见。"""
    from app.models.user import User
    other_user = User(
        email=f"other_{uuid.uuid4().hex[:8]}@test.local",
        name="Other",
        hashed_pw="x",
        is_active=True,
    )
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)

    project = await _make_committed_project(db, other_user.id)
    doc = await _make_committed_document(db)

    # other_user own 一篇
    _override_auth(other_user)
    try:
        await async_client.post(
            f"/api/projects/{project.id}/documents/{doc.id}/own",
            json={"source": "downloaded", "format": "pdf"},
        )
    finally:
        _clear_auth()

    # test_user 不应看到
    _override_auth(test_user)
    try:
        r = await async_client.get("/api/users/me/documents")
        assert r.json()["items"] == []
    finally:
        _clear_auth()
