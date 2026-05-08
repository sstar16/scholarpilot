"""TDD: refresh token lifecycle (issue / verify / revoke / rotate)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_tokens import (
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_refresh_token,
)


@pytest.mark.asyncio
async def test_issue_returns_plaintext_and_persists_hash(
    db: AsyncSession, test_user
):
    plaintext, model = await issue_refresh_token(
        db,
        user_id=test_user.id,
        client_type="desktop",
        client_version="0.1.0",
    )
    assert isinstance(plaintext, str)
    assert len(plaintext) >= 32
    assert model.token_hash != plaintext
    assert model.client_type == "desktop"
    assert model.client_version == "0.1.0"
    assert model.user_id == test_user.id


@pytest.mark.asyncio
async def test_verify_accepts_unrevoked_unexpired(
    db: AsyncSession, test_user
):
    plaintext, _ = await issue_refresh_token(db, user_id=test_user.id)
    record = await verify_refresh_token(db, plaintext)
    assert record is not None
    assert record.user_id == test_user.id


@pytest.mark.asyncio
async def test_verify_rejects_revoked(db: AsyncSession, test_user):
    plaintext, model = await issue_refresh_token(db, user_id=test_user.id)
    await revoke_refresh_token(db, model.id)
    record = await verify_refresh_token(db, plaintext)
    assert record is None


@pytest.mark.asyncio
async def test_verify_rejects_expired(db: AsyncSession, test_user):
    plaintext, model = await issue_refresh_token(db, user_id=test_user.id)
    model.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    record = await verify_refresh_token(db, plaintext)
    assert record is None


@pytest.mark.asyncio
async def test_rotate_revokes_old_and_issues_new(db: AsyncSession, test_user):
    old_plain, old_model = await issue_refresh_token(db, user_id=test_user.id)
    new_plain, new_model = await rotate_refresh_token(db, old_model)
    assert old_model.revoked_at is not None
    assert new_plain != old_plain
    assert new_model.user_id == old_model.user_id
    assert await verify_refresh_token(db, old_plain) is None
    assert await verify_refresh_token(db, new_plain) is not None
