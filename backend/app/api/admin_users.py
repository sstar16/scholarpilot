"""
Admin User Management API

提供 DevTools 用户监控与管理：
- 列出所有用户（含在线状态、项目数、邀请码使用数）
- 切换 is_admin / is_active
- 删除用户（硬删，带安全检查）
- 查看单个用户活动历史（projects、conversations、dev_logs 相关项）
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, cast, String
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.project import Project
from app.models.invitation_code import InvitationCode
from app.models.conversation_session import ConversationSession
from app.models.dev_log import DevLog
from app.dependencies import require_admin, LAST_SEEN_KEY_PREFIX


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


# ─── Schemas ───

class UserOut(BaseModel):
    id: str
    email: str
    name: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    last_seen_at: Optional[datetime] = None
    is_online: bool = False
    project_count: int = 0
    invited_by_code: Optional[str] = None  # 注册时使用的邀请码

    class Config:
        from_attributes = True


class UserPatch(BaseModel):
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None


class ActivityEvent(BaseModel):
    kind: str               # project_created | session_created | log
    timestamp: datetime
    title: str
    detail: Optional[str] = None
    level: Optional[str] = None


class UserActivity(BaseModel):
    user_id: str
    email: str
    name: str
    recent_projects: list[dict]
    recent_sessions: list[dict]
    recent_logs: list[dict]
    stats: dict


# ─── Helpers ───

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
            await r.close()
    except Exception:
        return {}


# ─── Endpoints ───

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
    """分页列出用户，带在线状态和项目数。"""
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
    # online 过滤在 Python 侧做（因为数据在 Redis）

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

    # 项目数（批量）
    proj_counts: dict[uuid.UUID, int] = {}
    if user_ids:
        pr = await db.execute(
            select(Project.user_id, func.count(Project.id))
            .where(Project.user_id.in_(user_ids))
            .group_by(Project.user_id)
        )
        for uid, cnt in pr.all():
            proj_counts[uid] = cnt

    # 注册时使用的邀请码
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
            project_count=proj_counts.get(u.id, 0),
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

    # 在线：MGET 所有 last_seen keys（用 SCAN 避免 KEYS）
    online = 0
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            async for _ in r.scan_iter(match=f"{LAST_SEEN_KEY_PREFIX}*"):
                online += 1
        finally:
            await r.close()
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
    """更新用户 is_admin / is_active / name。"""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 user_id")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 安全检查
    if patch.is_admin is False and user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能撤销自己的管理员权限")
    if patch.is_active is False and user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")

    # 避免删除最后一个管理员
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
    """硬删用户。会级联删除 projects（User.projects cascade=all, delete-orphan）。

    限制：
    - 不能删自己
    - 不能删最后一个管理员
    - 删除前解绑邀请码的 used_by 关联
    """
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

    # 解绑邀请码使用记录（created_by 和 used_by 都要处理，避免 FK 约束失败）
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


@router.get("/{user_id}/activity")
async def user_activity(
    user_id: str,
    days: int = Query(7, ge=1, le=90),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """单个用户的活动摘要（最近 N 天）。

    包含：
    - 最近项目
    - 最近对话 session
    - 最近 dev_logs（按 project_id 关联间接匹配）
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 user_id")

    r = await db.execute(select(User).where(User.id == uid))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 整个活动聚合用独立 try 包起来，任何一段挂了都返回空数据 + 把真实错误给前端
    projects: list[dict] = []
    project_uuids: list[uuid.UUID] = []
    sessions: list[dict] = []
    logs: list[dict] = []
    partial_errors: list[str] = []

    try:
        proj_rs = await db.execute(
            select(Project)
            .where(Project.user_id == uid)
            .order_by(Project.created_at.desc())
            .limit(20)
        )
        proj_list = list(proj_rs.scalars().all())
        for p in proj_list:
            projects.append({
                "id": str(p.id),
                "title": p.title,
                "domain": getattr(p, "domain", None),
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "current_round": getattr(p, "current_round", 0),
            })
            project_uuids.append(p.id)
    except Exception as e:
        logger.exception("activity projects query failed for user %s", uid)
        partial_errors.append(f"projects: {type(e).__name__}: {e}")

    try:
        sess_rs = await db.execute(
            select(ConversationSession)
            .where(ConversationSession.user_id == uid)
            .order_by(ConversationSession.created_at.desc())
            .limit(20)
        )
        for s in sess_rs.scalars().all():
            # 注意：ConversationSession 只有 created_at / updated_at，没有 last_activity_at
            sessions.append({
                "id": str(s.id),
                "project_id": str(s.project_id) if s.project_id else None,
                "current_state": s.current_state,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_activity_at": s.updated_at.isoformat() if s.updated_at else None,
            })
    except Exception as e:
        logger.exception("activity sessions query failed for user %s", uid)
        partial_errors.append(f"sessions: {type(e).__name__}: {e}")

    if project_uuids:
        try:
            log_rs = await db.execute(
                select(DevLog)
                .where(DevLog.project_id.in_(project_uuids))
                .where(DevLog.created_at >= since)
                .order_by(DevLog.created_at.desc())
                .limit(100)
            )
            for lg in log_rs.scalars().all():
                logs.append({
                    "id": lg.id,
                    "created_at": lg.created_at.isoformat() if lg.created_at else None,
                    "level": lg.level,
                    "source": lg.source,
                    "category": lg.category,
                    "message": lg.message,
                    "duration_ms": lg.duration_ms,
                    "project_id": str(lg.project_id) if lg.project_id else None,
                })
        except Exception as e:
            logger.exception("activity logs query failed for user %s", uid)
            partial_errors.append(f"logs: {type(e).__name__}: {e}")

    stats = {
        "total_projects": len(projects),
        "total_sessions": len(sessions),
        "log_events": len(logs),
        "errors": sum(1 for lg in logs if (lg.get("level") or "").lower() == "error"),
    }

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "recent_projects": projects,
        "recent_sessions": sessions,
        "recent_logs": logs,
        "stats": stats,
        "partial_errors": partial_errors,
    }
