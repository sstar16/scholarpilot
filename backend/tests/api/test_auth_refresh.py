"""/api/auth/refresh + /logout integration tests."""
import uuid

import pytest
from httpx import AsyncClient
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def _make_user(db: AsyncSession, password: str = "testpassword123") -> User:
    user = User(
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        name="Test User",
        hashed_pw=pwd_context.hash(password),
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    await db.refresh(user)
    return user


async def _login(async_client: AsyncClient, email: str, password: str = "testpassword123"):
    res = await async_client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_refresh_with_valid_token_rotates(
    async_client: AsyncClient, db: AsyncSession
):
    user = await _make_user(db)
    login_body = await _login(async_client, user.email)
    old_refresh = login_body["refresh_token"]

    res = await async_client.post(
        "/api/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_token"] != old_refresh  # rotate

    # 旧 refresh 不可再用（已 revoke）
    res2 = await async_client.post(
        "/api/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert res2.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_invalid_token_rejects(
    async_client: AsyncClient, db: AsyncSession
):
    res = await async_client.post(
        "/api/auth/refresh",
        json={"refresh_token": "totally-fake-not-real"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(
    async_client: AsyncClient, db: AsyncSession
):
    user = await _make_user(db)
    login_body = await _login(async_client, user.email)
    access = login_body["access_token"]
    refresh = login_body["refresh_token"]

    # logout 需要 access token (Bearer)
    res = await async_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {access}"},
        json={"refresh_token": refresh},
    )
    assert res.status_code == 204

    # 撤销后 refresh 不可用
    res2 = await async_client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert res2.status_code == 401
