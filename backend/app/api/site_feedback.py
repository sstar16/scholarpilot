"""
Site-wide User Feedback API
---------------------------

首页反馈按钮提交的用户产品反馈（bug / 建议 / 其他），
同时推送到管理员 Telegram（可配置；失败静默降级）。

路由：
  POST   /api/site-feedback               —— 任意用户（含匿名）提交反馈
  GET    /api/site-feedback/admin         —— admin 查看列表（分页 + 状态筛选）
  PATCH  /api/site-feedback/admin/{id}    —— admin 更新状态 / 写备注
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.user_feedback import UserFeedback
from app.services.telegram_notify import send_feedback_notification as send_telegram
from app.services.feishu_notify import send_feedback_notification as send_feishu

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/site-feedback", tags=["site-feedback"])


# ──────────── Schemas ────────────

_ALLOWED_CATEGORIES = {"bug", "suggestion", "praise", "other"}
_ALLOWED_STATUSES = {"open", "triaged", "resolved", "wontfix"}


class FeedbackSubmit(BaseModel):
    category: str = Field(default="other")
    content: str = Field(min_length=1, max_length=4000)
    contact: Optional[str] = Field(default=None, max_length=255)
    page_url: Optional[str] = Field(default=None, max_length=500)


class FeedbackOut(BaseModel):
    id: str
    user_id: Optional[str]
    user_email: Optional[str]
    category: str
    content: str
    contact: Optional[str]
    page_url: Optional[str]
    user_agent: Optional[str]
    status: str
    admin_note: Optional[str]
    created_at: str
    updated_at: str


class FeedbackPatch(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = Field(default=None, max_length=4000)


class FeedbackListOut(BaseModel):
    total: int
    items: list[FeedbackOut]


# ──────────── Helpers ────────────


def _row_to_out(r: UserFeedback) -> FeedbackOut:
    return FeedbackOut(
        id=str(r.id),
        user_id=str(r.user_id) if r.user_id else None,
        user_email=r.user_email_snapshot,
        category=r.category,
        content=r.content,
        contact=r.contact,
        page_url=r.page_url,
        user_agent=r.user_agent,
        status=r.status,
        admin_note=r.admin_note,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


def _require_admin(user: User) -> None:
    """允许管理员的条件（两者取并集）：
    - users.is_admin = True
    - email 匹配 settings.feedback_admin_email（便于内测期单账号 ad-hoc 开权限）
    """
    if getattr(user, "is_admin", False):
        return
    admin_email = (settings.feedback_admin_email or "").strip().lower()
    if admin_email and user.email and user.email.strip().lower() == admin_email:
        return
    raise HTTPException(status_code=403, detail="Admin only")


async def _maybe_get_current_user(
    request: Request, db: AsyncSession,
) -> Optional[User]:
    """登录态可选 —— 未带 token 也允许匿名提交反馈"""
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        from app.dependencies import _user_from_token
        return await _user_from_token(token, db)
    except HTTPException:
        return None
    except Exception:
        return None


# ──────────── Endpoints ────────────


@router.post("", response_model=FeedbackOut, status_code=201)
async def submit_feedback(
    body: FeedbackSubmit,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    category = body.category if body.category in _ALLOWED_CATEGORIES else "other"

    # 鉴权可选：带 token 则关联用户
    current_user = await _maybe_get_current_user(request, db)

    user_agent = (request.headers.get("user-agent") or "")[:500]

    fb = UserFeedback(
        user_id=current_user.id if current_user else None,
        user_email_snapshot=current_user.email if current_user else None,
        category=category,
        content=body.content.strip(),
        contact=(body.contact or "").strip() or None,
        page_url=(body.page_url or "").strip() or None,
        user_agent=user_agent or None,
        status="open",
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)

    # 异步双发通知（Telegram + 飞书），不阻塞响应；任一失败不影响另一个
    notify_kwargs = dict(
        feedback_id=str(fb.id),
        category=fb.category,
        content=fb.content,
        user_email=fb.user_email_snapshot,
        contact=fb.contact,
        page_url=fb.page_url,
    )
    try:
        asyncio.create_task(send_telegram(**notify_kwargs))
    except Exception as e:
        logger.warning("[site_feedback] 调度 Telegram 通知失败: %s", e)
    try:
        asyncio.create_task(send_feishu(**notify_kwargs))
    except Exception as e:
        logger.warning("[site_feedback] 调度 飞书 通知失败: %s", e)

    return _row_to_out(fb)


@router.get("/admin", response_model=FeedbackListOut)
async def list_feedback_admin(
    status_filter: Optional[str] = Query(None, alias="status"),
    category_filter: Optional[str] = Query(None, alias="category"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)

    conds = []
    if status_filter and status_filter in _ALLOWED_STATUSES:
        conds.append(UserFeedback.status == status_filter)
    if category_filter and category_filter in _ALLOWED_CATEGORIES:
        conds.append(UserFeedback.category == category_filter)

    total_q = select(func.count()).select_from(UserFeedback)
    list_q = select(UserFeedback).order_by(UserFeedback.created_at.desc())
    for c in conds:
        total_q = total_q.where(c)
        list_q = list_q.where(c)

    total = (await db.execute(total_q)).scalar() or 0
    rows = (await db.execute(list_q.limit(limit).offset(offset))).scalars().all()

    return FeedbackListOut(
        total=total,
        items=[_row_to_out(r) for r in rows],
    )


@router.patch("/admin/{feedback_id}", response_model=FeedbackOut)
async def update_feedback_admin(
    feedback_id: uuid.UUID,
    body: FeedbackPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(current_user)

    r = await db.execute(select(UserFeedback).where(UserFeedback.id == feedback_id))
    fb = r.scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")

    if body.status is not None:
        if body.status not in _ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status {body.status}")
        fb.status = body.status
    if body.admin_note is not None:
        fb.admin_note = body.admin_note.strip()
    fb.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(fb)

    return _row_to_out(fb)
