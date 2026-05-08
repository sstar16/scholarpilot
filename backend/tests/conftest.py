"""
Root conftest for backend integration tests.

Isolation strategy:
- `scholarpilot_test` database (never touches production `urip`)
- NullPool: each fixture call gets fresh connections on the current event loop
- `db` fixture: wraps each test in a SAVEPOINT → rolled back after the test
- `async_client`: uses an independent NullPool session (can't share asyncpg
  connections across asyncio task boundaries / Starlette middleware tasks)

asyncpg limitation: connections cannot be shared across asyncio Task boundaries.
The `async_client` therefore overrides get_db with its own session factory so
the ASGI app's DB calls stay within their own task context.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator

# M3: 启用 dev/test-only echo route（/api/_test/byok-echo）
# 生产 env 必须留空或设 "0"，避免 echo route 暴露 request.state
os.environ.setdefault("ENABLE_TEST_ECHO_ROUTES", "1")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TEST_DB_URL = (
    "postgresql+asyncpg://urip:Scholarpilot2026Strongdev"
    "@postgres:5432/scholarpilot_test"
)
_SYNC_TEST_DB_URL = _TEST_DB_URL.replace("postgresql+asyncpg", "postgresql")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_TABLES_CREATED = False


def _ensure_tables_once() -> None:
    """Sync one-shot Base.metadata.create_all — no async loop involvement."""
    global _TABLES_CREATED
    if _TABLES_CREATED:
        return
    import app.models  # noqa: registers all ORM models on Base
    from app.database import Base

    sync_engine = create_engine(_SYNC_TEST_DB_URL)
    try:
        Base.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()
    _TABLES_CREATED = True


def _make_engine():
    return create_async_engine(_TEST_DB_URL, poolclass=NullPool, echo=False)


# ---------------------------------------------------------------------------
# Function-scoped DB session with savepoint rollback
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    _ensure_tables_once()
    """
    AsyncSession for direct ORM work in tests.
    Uses explicit commit-per-flush + final DELETE cleanup so asyncpg never
    has a pending operation when teardown runs. Each fixture call gets a fresh
    NullPool connection (no cross-loop reuse).
    """
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session
        # Roll back any uncommitted state; ignore errors (e.g. already closed)
        try:
            await session.rollback()
        except Exception:
            pass

    await engine.dispose()


# ---------------------------------------------------------------------------
# HTTP client — independent NullPool sessions per request
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """
    httpx AsyncClient via ASGI transport.
    Overrides get_db with a NullPool factory so every request gets its own
    connection (required: asyncpg can't cross asyncio task boundaries).
    """
    _ensure_tables_once()
    from app.main import app
    from app.database import get_db

    engine = _make_engine()
    req_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_get_db():
        async with req_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _test_get_db
    try:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            follow_redirects=True,
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Test user
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_user(db: AsyncSession):
    """Fresh User per test (random email avoids unique constraint)."""
    from app.models.user import User

    user = User(
        email=f"test_{uuid.uuid4().hex[:8]}@test.local",
        name="Test User",
        hashed_pw=pwd_context.hash("testpassword123"),
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Auth headers (real JWT)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def auth_headers(test_user) -> dict[str, str]:
    """Authorization header dict with a real JWT for test_user."""
    from app.api.auth import create_access_token

    token = create_access_token(str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fresh project (current_round=0)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def fresh_project(db: AsyncSession, test_user):
    """Project with current_round=0 (scene FRESH)."""
    from app.models.project import Project

    project = Project(
        user_id=test_user.id,
        title="Test Project",
        description="Integration test project",
        domain="computer_science",
        current_round=0,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Factory: session in a given state
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def session_in_state(db: AsyncSession, test_user):
    """
    Factory returning a ConversationSession in the given state.

    Usage::

        session = await session_in_state("idle")
        session = await session_in_state("keyword_confirmation", metadata={...})
        session = await session_in_state("idle", project=my_project)
    """
    from app.models.conversation_session import ConversationSession

    async def _factory(
        state: str,
        metadata: dict | None = None,
        project=None,
    ) -> ConversationSession:
        sess = ConversationSession(
            user_id=test_user.id,
            project_id=project.id if project else None,
            current_state=state,
            state_data=metadata or {},
            messages=[],
        )
        db.add(sess)
        await db.flush()
        await db.refresh(sess)
        return sess

    return _factory


# ---------------------------------------------------------------------------
# Factory: session + active round
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def session_with_active_round(db: AsyncSession, test_user):
    """
    Factory returning (ConversationSession, SearchRound).
    Creates its own Project inline (NOT via fresh_project fixture) to avoid
    the asyncpg cross-fixture protocol-state issue observed with shared
    objects across fixture invocations.

    The round has status='searching'; session.state_data['current_round_id'] is set.

    Usage::

        session, round = await session_with_active_round("keyword_confirmation")
    """
    from app.models.conversation_session import ConversationSession
    from app.models.project import Project
    from app.models.search_round import SearchRound

    async def _factory(state: str):
        project = Project(
            user_id=test_user.id,
            title="Active-round Test Project",
            description="Integration test project",
            domain="computer_science",
            current_round=1,
        )
        db.add(project)
        await db.flush()

        round_ = SearchRound(
            project_id=project.id,
            round_number=1,
            status="searching",
        )
        db.add(round_)
        await db.flush()
        await db.refresh(round_)

        sess = ConversationSession(
            user_id=test_user.id,
            project_id=project.id,
            current_state=state,
            state_data={"current_round_id": str(round_.id)},
            messages=[],
        )
        db.add(sess)
        await db.flush()
        await db.refresh(sess)

        return sess, round_

    return _factory


# ---------------------------------------------------------------------------
# Convenience: idle session
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def fresh_session(session_in_state):
    """Equivalent to await session_in_state('idle')."""
    return await session_in_state("idle")
