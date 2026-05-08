"""Channel registry — 单例 dict，启动时填充。

V1 注册：feishu / serverchan / email / telegram
V2 可加：wxpusher / pushplus / wecom

API：
    get_channel("feishu") -> FeishuChannel instance
    list_channels() -> [(channel_id, display_name, config_kind), ...]
"""
from __future__ import annotations

from typing import Optional

from app.services.notifications.base import NotificationChannel
from app.services.notifications.email import EmailChannel
from app.services.notifications.feishu import FeishuChannel
from app.services.notifications.serverchan import ServerChanChannel
from app.services.notifications.telegram import TelegramChannel


# 不可变注册表；新增 channel 在此显式列出（避免 import 顺序坑）
_CHANNELS: dict[str, NotificationChannel] = {
    FeishuChannel.channel_id: FeishuChannel(),
    ServerChanChannel.channel_id: ServerChanChannel(),
    EmailChannel.channel_id: EmailChannel(),
    TelegramChannel.channel_id: TelegramChannel(),
}


def get_channel(channel_id: str) -> Optional[NotificationChannel]:
    return _CHANNELS.get(channel_id)


def list_channels() -> list[dict]:
    """返回前端展示用的 channel 列表。"""
    return [
        {
            "channel_id": ch.channel_id,
            "display_name": ch.display_name,
            "config_kind": ch.config_kind,
        }
        for ch in _CHANNELS.values()
    ]
