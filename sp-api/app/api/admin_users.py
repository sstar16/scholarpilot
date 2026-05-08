"""
Admin User Management API — sp-api 版（删 projects/conversation_sessions 依赖）。

vs backend/app/api/admin_users.py 改动：
- list_users 不再带 project_count（sp-api 没有 projects 表）
- user_activity endpoint 改为：仅返 dev_logs（按 user_id 找不到 — DevLog 没 user_id 字段，
  只能按 client_run_id / project_id 关联，sp-api 不存这映射）。简化为只返 user 基本信息 + 邀请码。
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import LAST_SEEN_KEY_PREFIX, require_admin
from app.models.invitation_code import InvitationCode
from app.models.user import User


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    last_seen_at: Optional[datetime] = None
    is_online: bool = False
    invited_by_code: Optional[str] = None

    class Config:
        from_attributes = True


class UserPatch(BaseModel):
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None


async def _get_online_map(user_ids: list[uuid.UUID]) -> dict[str, datetime]:
    """批量 MGET Redis last_seen。返回 {user_id_str: datetime} 只包含还在 TTL 内的。"""
    if not user_ids:
        return {}
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            keys = [f"{LAST_SEEN_KEY_PREFIX}{uid}" for uid in user_ids]
            values = await r.mget(keys)
            out: dict[str, datetime] = {}
            for uid, val in zip(user_ids, values):
                if val:
                    try:
                        out[str(uid)] = datetime.fromisoformat(val)
                    except ValueError:
                        pass
            return out
        finally:
            await r.aclose()
    except Exception:
        return {}


@router.get("", response_model=dict)
async def list_users(
    search: Optional[str] = Query(None, description="邮箱或用户名模糊搜索"),
    status_filter: Optional[str] = Query(None, alias="status",
                                         description="all / online / admin / inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """分页列出用户，带在线状态和邀请码（sp-api 无 project_count）。"""
    base = select(User)
    if search:
        term = f"%{search.lower()}%"
        base = base.where(or_(
            func.lower(User.email).like(term),
            func.lower(User.name).like(term),
        ))
    if status_filter == "admin":
        base = base.where(User.is_admin.is_(True))
    elif status_filter == "inactive":
        base = base.where(User.is_active.is_(False))

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    result = await db.execute(
        base.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = list(result.scalars().all())
    user_ids = [u.id for u in users]

    inv_map: dict[uuid.UUID, str] = {}
    if user_ids:
        ir = await db.execute(
            select(InvitationCode.used_by, InvitationCode.code)
            .where(InvitationCode.used_by.in_(user_ids))
        )
        for uid, code in ir.all():
            inv_map[uid] = code

    online_map = await _get_online_map(user_ids)
    now = datetime.now(timezone.utc)

    items: list[UserOut] = []
    for u in users:
        last_seen = online_map.get(str(u.id))
        is_online = last_seen is not None and (now - last_seen).total_seconds() <= 120
        items.append(UserOut(
            id=str(u.id),
            email=u.email,
            name=u.name,
            is_active=u.is_active,
            is_admin=u.is_admin,
            created_at=u.created_at,
            last_seen_at=last_seen,
            is_online=is_online,
            invited_by_code=inv_map.get(u.id),
        ))

    if status_filter == "online":
        items = [it for it in items if it.is_online]

    return {
        "items": [it.model_dump() for it in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats")
async def user_stats(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """用户总量 / admin 数 / 禁用数 / 今日新增 / 当前在线。"""
    total = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    admins = (await db.execute(
        select(func.count()).select_from(User).where(User.is_admin.is_(True))
    )).scalar_one()
    inactive = (await db.execute(
        select(func.count()).select_from(User).where(User.is_active.is_(False))
    )).scalar_one()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = (await db.execute(
        select(func.count()).select_from(User).where(User.created_at >= today_start)
    )).scalar_one()

    online = 0
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            async for _ in r.scan_iter(match=f"{LAST_SEEN_KEY_PREFIX}*"):
                online += 1
        finally:
            await r.aclose()
    except Exception:
        pass

    return {
        "total": total,
        "admins": admins,
        "inactive": inactive,
        "new_today": new_today,
        "online": online,
    }


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    patch: UserPatch,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 user_id")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if patch.is_admin is False and user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能撤销自己的管理员权限")
    if patch.is_active is False and user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")

    if patch.is_admin is False and user.is_admin:
        admin_count = (await db.execute(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )).scalar_one()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="至少需要保留一个管理员")

    if patch.is_admin is not None:
        user.is_admin = patch.is_admin
    if patch.is_active is not None:
        user.is_active = patch.is_active
    if patch.name is not None:
        user.name = patch.name.strip()[:100]

    await db.commit()
    await db.refresh(user)

    return UserOut(
        id=str(user.id),
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """硬删用户。sp-api 无 projects 级联，仅解绑邀请码 used_by/created_by。"""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 user_id")

    if uid == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if user.is_admin:
        admin_count = (await db.execute(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        )).scalar_one()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个管理员")

    await db.execute(
        InvitationCode.__table__.update()
        .where(InvitationCode.used_by == uid)
        .values(used_by=None)
    )
    await db.execute(
        InvitationCode.__table__.update()
        .where(InvitationCode.created_by == uid)
        .values(created_by=None)
    )

    await db.delete(user)
    await db.commit()
