"""Notification channels — V1: 飞书 / 微信 Server酱 / 邮件 / Telegram。

详细调研见 wiki/notification-channels-china.md。

使用：
    from app.services.notifications import NotificationDispatcher, NotificationPayload

    await NotificationDispatcher.dispatch(
        db=db,
        user_id=user.id,
        payload=NotificationPayload(
            title="ScholarPilot 每日推送",
            body="今日检索到 5 篇文献...",
            links=[("查看", "https://...")],
        ),
    )

设计：
    - NotificationChannel ABC：每种通道一个实现类
    - NotificationDispatcher：按 user 设置并行分发，单 channel 失败不影响其他
    - 配置 webhook URL / send key 等敏感字段加密存（services/notifications/crypto.py）
"""
from app.services.notifications.base import (
    NotificationChannel,
    NotificationPayload,
    NotificationResult,
)
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.notifications.registry import (
    get_channel,
    list_channels,
)

__all__ = [
    "NotificationChannel",
    "NotificationPayload",
    "NotificationResult",
    "NotificationDispatcher",
    "get_channel",
    "list_channels",
]
