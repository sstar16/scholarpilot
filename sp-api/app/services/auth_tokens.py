"""Refresh token lifecycle: issue / verify / revoke / rotate.

明文 token 仅在 issue/rotate 返回值里出现，DB 存 SHA-256 hash。
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.refresh_token import RefreshToken


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


async def issue_refresh_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    client_type: str = "desktop",
    client_version: str | None = None,
) -> tuple[str, RefreshToken]:
    plaintext = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    record = RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(plaintext),
        client_type=client_type,
        client_version=client_version,
        issued_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return plaintext, record


async def verify_refresh_token(
    db: AsyncSession, plaintext: str
) -> RefreshToken | None:
    token_hash = _hash_token(plaintext)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    if record is None or not record.is_active():
        return None
    record.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return record


async def revoke_refresh_token(db: AsyncSession, token_id: UUID) -> None:
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.id == token_id)
    )
    record = result.scalar_one_or_none()
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        await db.commit()


async def rotate_refresh_token(
    db: AsyncSession, old: RefreshToken
) -> tuple[str, RefreshToken]:
    """撤销旧 token + 签发新 token，原子操作。"""
    now = datetime.now(timezone.utc)
    old.revoked_at = now
    new_plain = secrets.token_urlsafe(48)
    new_record = RefreshToken(
        user_id=old.user_id,
        token_hash=_hash_token(new_plain),
        client_type=old.client_type,
        client_version=old.client_version,
        issued_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(new_record)
    await db.commit()
    await db.refresh(new_record)
    return new_plain, new_record
