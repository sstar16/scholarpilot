"""login 返回 access + refresh + expires_in（double-token contract）

注意：conftest 的 test_user fixture 用 `@test.local` 域名，
EmailStr 会拒（reserved name），所以这里 inline 建 user 用 @example.com。
"""
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


@pytest.mark.asyncio
async def test_login_returns_access_and_refresh(
    async_client: AsyncClient, db: AsyncSession
):
    user = await _make_user(db)
    res = await async_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "testpassword123"},
        headers={
            "X-Client-Type": "desktop",
            "X-Client-Version": "0.1.0",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20
    assert isinstance(body["refresh_token"], str) and len(body["refresh_token"]) >= 48
    assert body["token_type"] == "bearer"
    # expires_in 跟 settings 实际值（受 .env 覆盖）一致
    from app.config import settings
    assert body["expires_in"] == settings.access_token_expire_minutes * 60


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(
    async_client: AsyncClient, db: AsyncSession
):
    user = await _make_user(db)
    res = await async_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "wrongpw"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_login_persists_refresh_token_with_client_meta(
    async_client: AsyncClient, db: AsyncSession
):
    """login 调用应在 refresh_tokens 表为该 user 留一条记录，附带 client_type/version。"""
    from sqlalchemy import select
    from app.models.refresh_token import RefreshToken

    user = await _make_user(db)
    res = await async_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "testpassword123"},
        headers={
            "X-Client-Type": "android",
            "X-Client-Version": "0.2.0",
        },
    )
    assert res.status_code == 200

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    rows = result.scalars().all()
    assert len(rows) >= 1
    last = max(rows, key=lambda r: r.issued_at)
    assert last.client_type == "android"
    assert last.client_version == "0.2.0"
    assert last.revoked_at is None
