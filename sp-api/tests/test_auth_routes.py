"""Auth routes — 路由存在性 + register 业务逻辑（fake DB）。

2026-05-08 新增：客户端注册开放（X-Client-Type=desktop 跳过邀请码）+ 首位用户自动 admin。
为不依赖 PostgreSQL 跑 register 端到端，测试通过 FastAPI dep override 注入 fake AsyncSession。
"""
import uuid
from typing import Any

from fastapi.testclient import TestClient


def _get_app():
    from app.main import app
    return app


def test_auth_login_route_exists():
    """POST /api/auth/login 存在。无 DB 时会返 5xx，但路由本身要在。"""
    app = _get_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/auth/login", json={"email": "x@y.z", "password": "p"})
    # 不应 404；可能 401（凭证错）/ 422（schema 不对）/ 500（DB 不通）
    assert r.status_code != 404, f"login route missing: {r.status_code}"


def test_auth_register_route_exists():
    app = _get_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/auth/register", json={
        "email": "x@y.z", "name": "x", "password": "p", "invitation_code": "x",
    })
    assert r.status_code != 404


def test_auth_me_requires_token():
    app = _get_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/auth/me")
    # 无 token → 401
    assert r.status_code == 401


def test_health_no_llm_field():
    """V9 验收：sp-api 的 /health 不含 llm 字段。"""
    app = _get_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "llm" not in body, "sp-api /health 不应返回 llm 字段"
    assert body.get("status") == "ok"
    assert "sources" in body


# ────────────────────────────────────────────────────────────────────
# 2026-05-08 新增：register 业务逻辑测试（desktop 跳邀请码 / 首位 admin）
# ────────────────────────────────────────────────────────────────────


class _FakeResult:
    """sqlalchemy execute() 返回值的最小子集 — scalar_one_or_none / scalar_one / all。"""

    def __init__(self, rows: list[Any] | None = None, scalar_value: Any = None):
        self._rows = rows or []
        self._scalar = scalar_value

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else 0

    def scalars(self):
        class _S:
            def __init__(self, rows):
                self._rows = rows
            def all(self):
                return list(self._rows)
            def first(self):
                return self._rows[0] if self._rows else None
        return _S(self._rows)

    def all(self):
        return list(self._rows)


class _FakeSession:
    """最小 AsyncSession 仿真：覆盖 register 与 issue_refresh_token 用到的方法。

    支持的查询场景：
      - select(User).where(User.email == ...)   → users_by_email
      - select(InvitationCode).where(...code == ...) → invitations_by_code
      - select(func.count(User.id))             → user_count
    其它统一返回空。
    """

    def __init__(self, *, users=None, invitations=None):
        self.users = users or {}              # email -> User
        self.invitations = invitations or {}  # code -> InvitationCode
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt):
        # 通过 stmt 字符串简单分类（sqlalchemy 内部生成的 SQL 文本）
        s = str(stmt).lower()
        # count
        if "count(" in s and "users" in s:
            return _FakeResult(scalar_value=len(self.users))
        # users where email = :email
        if "from users" in s and "email" in s:
            # 取 stmt.compile() 的 params
            try:
                params = stmt.compile().params
            except Exception:
                params = {}
            email = params.get("email_1") or params.get("email")
            if email and email in self.users:
                return _FakeResult([self.users[email]])
            return _FakeResult([])
        # invitation_codes where code = :code
        if "invitation_codes" in s and "code" in s:
            try:
                params = stmt.compile().params
            except Exception:
                params = {}
            code = params.get("code_1") or params.get("code")
            if code and code in self.invitations:
                return _FakeResult([self.invitations[code]])
            return _FakeResult([])
        # refresh_tokens / others → 空
        return _FakeResult([])

    def add(self, obj):
        self.added.append(obj)
        # 给 User 编 id；issue_refresh_token 也会 add()
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()
        # 注册 email→user 立刻可被 dependent 读出
        if hasattr(obj, "email") and hasattr(obj, "hashed_pw"):
            self.users[obj.email] = obj

    async def flush(self):
        for obj in self.added:
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        # 模拟数据库回填 created_at 等
        from datetime import datetime, timezone
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    async def close(self):
        pass

    async def rollback(self):
        pass


def _override_db(app, session: _FakeSession):
    from app.database import get_db

    async def _gen():
        yield session

    app.dependency_overrides[get_db] = _gen


def test_register_desktop_skips_invitation_code():
    """X-Client-Type=desktop + 不传邀请码 → 201 注册成功。"""
    app = _get_app()
    fake = _FakeSession()
    _override_db(app, fake)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/auth/register",
            json={"email": "alice@example.com", "name": "Alice", "password": "secret123"},
            headers={"X-Client-Type": "desktop", "X-Client-Version": "9.9.9"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body.get("access_token")
        assert body.get("refresh_token")
        assert "alice@example.com" in fake.users
    finally:
        app.dependency_overrides.clear()


def test_register_web_requires_invitation_code():
    """非 desktop（web 默认）+ 不传邀请码 → 400。"""
    app = _get_app()
    fake = _FakeSession()
    _override_db(app, fake)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/auth/register",
            json={"email": "bob@example.com", "name": "Bob", "password": "secret123"},
            # 不带 X-Client-Type → middleware 默认 "web"
        )
        assert r.status_code == 400, r.text
        assert "邀请码" in r.text
    finally:
        app.dependency_overrides.clear()


def test_register_first_user_is_admin():
    """空 DB + desktop 注册 → 首位用户 is_admin=True。"""
    app = _get_app()
    fake = _FakeSession()
    _override_db(app, fake)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/auth/register",
            json={"email": "first@example.com", "name": "First", "password": "secret123"},
            headers={"X-Client-Type": "desktop", "X-Client-Version": "9.9.9"},
        )
        assert r.status_code == 201, r.text
        user = fake.users["first@example.com"]
        assert user.is_admin is True, "首位注册用户应自动 is_admin"
    finally:
        app.dependency_overrides.clear()


def test_register_second_user_not_admin():
    """已有用户时 → 第 2+ 用户 is_admin=False。"""
    app = _get_app()
    # 预置一个 admin
    from app.models.user import User as UserModel
    existing = UserModel(
        id=uuid.uuid4(),
        email="admin@example.com",
        name="Admin",
        hashed_pw="x",
        is_admin=True,
    )
    fake = _FakeSession(users={"admin@example.com": existing})
    _override_db(app, fake)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/auth/register",
            json={"email": "second@example.com", "name": "Second", "password": "secret123"},
            headers={"X-Client-Type": "desktop", "X-Client-Version": "9.9.9"},
        )
        assert r.status_code == 201, r.text
        user = fake.users["second@example.com"]
        assert user.is_admin is False, "第 2+ 用户不应自动 admin"
    finally:
        app.dependency_overrides.clear()
