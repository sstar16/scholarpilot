"""Dispatcher — 把 payload 分发给某个 user 启用的所有 channels。

设计：
  - asyncio.gather(*sends, return_exceptions=True) 并行分发
  - 单 channel 失败不影响其他（channel.send 已捕获异常）
  - 收集结果写 dev_logs（INFO/WARNING）方便事后查
  - 不阻塞主流程：上层调用方应 await 此方法或 fire-and-forget

使用：
    results = await NotificationDispatcher.dispatch(
        db=db, user_id=user.id, payload=...,
    )
    n_ok = sum(1 for r in results if r.ok)
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_notification_setting import UserNotificationSetting
from app.services.notifications.base import (
    NotificationPayload,
    NotificationResult,
)
from app.services.notifications.registry import get_channel

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    @staticmethod
    async def list_user_settings(
        db: AsyncSession, user_id: uuid.UUID, *, active_only: bool = True,
    ) -> list[UserNotificationSetting]:
        q = select(UserNotificationSetting).where(
            UserNotificationSetting.user_id == user_id
        )
        if active_only:
            q = q.where(UserNotificationSetting.is_active.is_(True))
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def dispatch(
        *,
        db: AsyncSession,
        user_id: uuid.UUID,
        payload: NotificationPayload,
    ) -> list[NotificationResult]:
        """对一个 user 推送到他全部 active channels。返回每个 channel 的结果。"""
        rows = await NotificationDispatcher.list_user_settings(
            db, user_id, active_only=True,
        )
        if not rows:
            logger.info("[notify] user=%s no active channels", user_id)
            return []

        async def _send_one(row: UserNotificationSetting) -> NotificationResult:
            ch = get_channel(row.channel)
            if ch is None:
                return NotificationResult(
                    row.channel, False,
                    f"channel '{row.channel}' not registered (deprecated?)",
                )
            try:
                return await ch.send(row.config_json or {}, payload)
            except Exception as e:
                # channel.send 不该抛错，但兜底
                logger.exception("[notify] channel %s raised: %s", row.channel, e)
                return NotificationResult(row.channel, False, f"unhandled: {e}")

        results = await asyncio.gather(
            *[_send_one(r) for r in rows], return_exceptions=False,
        )

        for r in results:
            if r.ok:
                logger.info("[notify] user=%s channel=%s ok", user_id, r.channel)
            else:
                logger.warning(
                    "[notify] user=%s channel=%s failed: %s",
                    user_id, r.channel, r.message,
                )
        return list(results)

    @staticmethod
    async def test_channel(
        *,
        channel_id: str,
        config: dict,
        payload: NotificationPayload,
    ) -> NotificationResult:
        """无 DB 依赖的单 channel 测试 — 用户在客户端点"测试连接"时调用。"""
        ch = get_channel(channel_id)
        if ch is None:
            return NotificationResult(channel_id, False, "unknown channel")
        try:
            return await ch.send(config, payload)
        except Exception as e:
            return NotificationResult(channel_id, False, f"unhandled: {e}")
