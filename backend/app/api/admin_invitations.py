import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from app.database import get_db
from app.models.user import User
from app.models.invitation_code import InvitationCode
from app.dependencies import get_current_user


router = APIRouter(prefix="/api/admin/invitations", tags=["admin-invitations"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


class GenerateRequest(BaseModel):
    count: int = 1
    note: str | None = None
    expires_in_days: int | None = None  # None = 永不过期


class InvitationOut(BaseModel):
    id: str
    code: str
    note: str | None
    created_at: datetime
    expires_at: datetime | None
    used_at: datetime | None
    used_by_email: str | None = None

    class Config:
        from_attributes = True


@router.post("", response_model=list[InvitationOut])
async def generate(
    req: GenerateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if req.count < 1 or req.count > 200:
        raise HTTPException(status_code=400, detail="count 必须在 1-200 之间")

    expires_at = None
    if req.expires_in_days is not None and req.expires_in_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_in_days)

    codes = []
    for _ in range(req.count):
        code_str = secrets.token_hex(8)  # 16 字符 hex
        inv = InvitationCode(
            code=code_str,
            note=req.note,
            created_by=admin.id,
            expires_at=expires_at,
        )
        db.add(inv)
        codes.append(inv)
    await db.commit()
    for c in codes:
        await db.refresh(c)

    return [
        InvitationOut(
            id=str(c.id), code=c.code, note=c.note,
            created_at=c.created_at, expires_at=c.expires_at, used_at=c.used_at,
        )
        for c in codes
    ]


@router.get("", response_model=list[InvitationOut])
async def list_codes(
    status: Literal["all", "unused", "used", "expired"] = Query("all"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(InvitationCode).order_by(InvitationCode.created_at.desc())
    if status == "unused":
        stmt = stmt.where(InvitationCode.used_at.is_(None))
        stmt = stmt.where(
            (InvitationCode.expires_at.is_(None)) | (InvitationCode.expires_at > datetime.now(timezone.utc))
        )
    elif status == "used":
        stmt = stmt.where(InvitationCode.used_at.is_not(None))
    elif status == "expired":
        stmt = stmt.where(InvitationCode.expires_at.is_not(None))
        stmt = stmt.where(InvitationCode.expires_at <= datetime.now(timezone.utc))
        stmt = stmt.where(InvitationCode.used_at.is_(None))

    result = await db.execute(stmt)
    codes = result.scalars().all()

    # 带出 used_by 的 email
    user_ids = {c.used_by for c in codes if c.used_by}
    emails: dict = {}
    if user_ids:
        ur = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in ur.scalars().all():
            emails[u.id] = u.email

    return [
        InvitationOut(
            id=str(c.id), code=c.code, note=c.note,
            created_at=c.created_at, expires_at=c.expires_at, used_at=c.used_at,
            used_by_email=emails.get(c.used_by) if c.used_by else None,
        )
        for c in codes
    ]


@router.delete("/{code_id}", status_code=204)
async def delete_code(
    code_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid
    try:
        uid = _uuid.UUID(code_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 code_id")

    result = await db.execute(select(InvitationCode).where(InvitationCode.id == uid))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    if code.used_at is not None:
        raise HTTPException(status_code=400, detail="已使用的邀请码不能删除")
    await db.delete(code)
    await db.commit()


@router.get("/stats")
async def stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    total = (await db.execute(select(func.count()).select_from(InvitationCode))).scalar_one()
    used = (await db.execute(
        select(func.count()).select_from(InvitationCode).where(InvitationCode.used_at.is_not(None))
    )).scalar_one()
    expired = (await db.execute(
        select(func.count()).select_from(InvitationCode)
        .where(InvitationCode.used_at.is_(None))
        .where(InvitationCode.expires_at.is_not(None))
        .where(InvitationCode.expires_at <= now)
    )).scalar_one()
    return {
        "total": total,
        "used": used,
        "expired": expired,
        "available": total - used - expired,
    }
