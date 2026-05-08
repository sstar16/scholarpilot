"""User notification settings API。

路由：
  GET    /api/users/me/notifications              —— 列出当前用户所有通道配置
  GET    /api/users/me/notifications/channels     —— 列出可用 channels（前端展示选项）
  POST   /api/users/me/notifications              —— 新增/更新（upsert）
  DELETE /api/users/me/notifications/{channel}    —— 删除
  POST   /api/users/me/notifications/{channel}/toggle —— 启用/禁用
  POST   /api/users/me/notifications/test         —— 不持久化的测试发送
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.user_notification_setting import (
    ALLOWED_CHANNELS,
    UserNotificationSetting,
)
from app.services.notifications import (
    NotificationDispatcher,
    NotificationPayload,
    list_channels,
)
from app.services.notifications.registry import get_channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users/me/notifications", tags=["notifications"])


# ─── Schemas ──────────────────────────────────────────────


class ChannelMetaOut(BaseModel):
    channel_id: str
    display_name: str
    config_kind: str  # 'webhook' | 'email' | 'telegram'


class NotificationSettingOut(BaseModel):
    id: str
    channel: str
    config: dict  # 脱敏后的视图（webhook URL masked 等）
    is_active: bool
    created_at: str
    updated_at: str


class NotificationUpsert(BaseModel):
    channel: str = Field(..., description="飞书/Server酱/邮件/Telegram 等")
    config: dict = Field(default_factory=dict, description="channel 特化配置（明文）")
    is_active: bool = True


class NotificationTestRequest(BaseModel):
    channel: str
    config: dict
    title: Optional[str] = None
    body: Optional[str] = None


class NotificationToggleRequest(BaseModel):
    is_active: bool


# ─── Helpers ──────────────────────────────────────────────


def _row_to_out(r: UserNotificationSetting) -> NotificationSettingOut:
    ch = get_channel(r.channel)
    if ch is None:
        view = {"_warning": f"unknown channel: {r.channel}"}
    else:
        try:
            view = ch.public_view(r.config_json or {})
        except Exception as e:
            view = {"_error": f"failed to render: {e}"}
    return NotificationSettingOut(
        id=str(r.id),
        channel=r.channel,
        config=view,
        is_active=r.is_active,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


# ─── Routes ──────────────────────────────────────────────


@router.get("/channels", response_model=list[ChannelMetaOut])
async def list_available_channels(_user: User = Depends(get_current_user)):
    """返回平台可用的 channel 列表（前端绑定时下拉选项）。"""
    return [ChannelMetaOut(**ch) for ch in list_channels()]


@router.get("", response_model=list[NotificationSettingOut])
async def list_my_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(UserNotificationSetting)
        .where(UserNotificationSetting.user_id == user.id)
        .order_by(UserNotificationSetting.created_at.asc())
    )).scalars().all()
    return [_row_to_out(r) for r in rows]


@router.post("", response_model=NotificationSettingOut)
async def upsert_setting(
    body: NotificationUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建或更新当前用户某 channel 的配置（user × channel 唯一）。"""
    if body.channel not in ALLOWED_CHANNELS:
        raise HTTPException(400, f"channel must be one of {ALLOWED_CHANNELS}")
    ch = get_channel(body.channel)
    if ch is None:
        raise HTTPException(400, f"channel '{body.channel}' not registered")

    try:
        encrypted_config = ch.validate_config(body.config)
    except ValueError as e:
        raise HTTPException(400, f"invalid config: {e}")

    existing = (await db.execute(
        select(UserNotificationSetting).where(
            UserNotificationSetting.user_id == user.id,
            UserNotificationSetting.channel == body.channel,
        )
    )).scalar_one_or_none()

    if existing:
        existing.config_json = encrypted_config
        existing.is_active = body.is_active
        await db.commit()
        await db.refresh(existing)
        return _row_to_out(existing)

    row = UserNotificationSetting(
        user_id=user.id,
        channel=body.channel,
        config_json=encrypted_config,
        is_active=body.is_active,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _row_to_out(row)


@router.post("/{channel}/toggle", response_model=NotificationSettingOut)
async def toggle_setting(
    channel: str,
    body: NotificationToggleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if channel not in ALLOWED_CHANNELS:
        raise HTTPException(400, f"channel must be one of {ALLOWED_CHANNELS}")
    row = (await db.execute(
        select(UserNotificationSetting).where(
            UserNotificationSetting.user_id == user.id,
            UserNotificationSetting.channel == channel,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "setting not found")
    row.is_active = body.is_active
    await db.commit()
    await db.refresh(row)
    return _row_to_out(row)


@router.delete("/{channel}", status_code=204)
async def delete_setting(
    channel: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if channel not in ALLOWED_CHANNELS:
        raise HTTPException(400, f"channel must be one of {ALLOWED_CHANNELS}")
    await db.execute(
        delete(UserNotificationSetting).where(
            UserNotificationSetting.user_id == user.id,
            UserNotificationSetting.channel == channel,
        )
    )
    await db.commit()
    return None


@router.post("/test")
async def test_send(
    body: NotificationTestRequest,
    user: User = Depends(get_current_user),
):
    """实时测试推送 — 不写 DB，直接用客户端传的明文 config 发一条测试消息。

    注意：客户端如果想测"已存在的 setting 是否还能发"，应另查 GET /api/users/me/notifications
    再用其中 config 调本接口（前端拼装）。本接口不暴露 server 端解密的明文。
    """
    if body.channel not in ALLOWED_CHANNELS:
        raise HTTPException(400, f"channel must be one of {ALLOWED_CHANNELS}")
    ch = get_channel(body.channel)
    if ch is None:
        raise HTTPException(400, f"channel '{body.channel}' not registered")

    try:
        encrypted_config = ch.validate_config(body.config)
    except ValueError as e:
        raise HTTPException(400, f"invalid config: {e}")

    payload = NotificationPayload(
        title=body.title or "ScholarPilot 测试推送",
        body=body.body or (
            f"这是一条测试消息，来自用户 {user.email}。\n"
            f"如果您看到这条消息，说明此通道工作正常。"
        ),
    )
    result = await NotificationDispatcher.test_channel(
        channel_id=body.channel,
        config=encrypted_config,
        payload=payload,
    )
    return {
        "ok": result.ok,
        "message": result.message,
        "channel": result.channel,
        "response_body": result.response_body,
    }
