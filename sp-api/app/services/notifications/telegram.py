"""Telegram bot channel — 复用现有 services/telegram_notify.py 的 token 配置。

注意：和现有 telegram_notify 的语义不同
  - 现有的：admin 收 site_feedback 通知，token + chat_id 配在 settings
  - 这里：用户配自己的 chat_id 收推送（bot token 仍用平台配置）

用户绑定流程：
  1. 用户先 search 平台 bot（用户用 /start 把自己加进 bot）
  2. 用户在 bot 里发 /chatid 命令（bot 端 V2 实现），bot 回 user.chat_id
  3. 用户把 chat_id 填到客户端 → 落 DB

config_json:
    {"chat_id": "123456"}

国内服务器 → api.telegram.org 走 settings.telegram_api_base（CF Worker 反代）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

import httpx

from app.config import settings
from app.services.notifications.base import (
    NotificationChannel,
    NotificationPayload,
    NotificationResult,
)

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class TelegramChannel(NotificationChannel):
    channel_id: ClassVar[str] = "telegram"
    display_name: ClassVar[str] = "Telegram"
    config_kind: ClassVar[str] = "telegram"

    async def send(
        self, config: dict, payload: NotificationPayload,
    ) -> NotificationResult:
        token = (settings.telegram_bot_token or "").strip()
        if not token:
            return NotificationResult(
                self.channel_id, False,
                "platform telegram_bot_token not configured",
            )
        chat_id = (config.get("chat_id") or "").strip()
        if not chat_id:
            return NotificationResult(self.channel_id, False, "chat_id empty")

        lines = [
            f"<b>{_escape_html(payload.title)}</b>",
            "",
            _escape_html(payload.body),
        ]
        if payload.links:
            lines.append("")
            for label, url in payload.links:
                lines.append(f'<a href="{_escape_html(url)}">{_escape_html(label)}</a>')
        message = "\n".join(lines)

        api_base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
        url = f"{api_base}/bot{token}/sendMessage"

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": settings.notification_user_agent},
            ) as client:
                resp = await client.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            return NotificationResult(self.channel_id, False, f"connect error: {e}")
        except asyncio.TimeoutError:
            return NotificationResult(self.channel_id, False, "timeout")
        except Exception as e:
            return NotificationResult(self.channel_id, False, f"unexpected: {e}")

        if resp.status_code != 200:
            return NotificationResult(
                self.channel_id, False,
                f"HTTP {resp.status_code}", response_body=resp.text[:200],
            )
        try:
            body = resp.json()
        except Exception:
            return NotificationResult(self.channel_id, False, "invalid json", resp.text[:200])
        if body.get("ok"):
            return NotificationResult(self.channel_id, True, "ok")
        return NotificationResult(
            self.channel_id, False,
            f"api error: {body.get('description')}",
            response_body=str(body)[:200],
        )

    @classmethod
    def validate_config(cls, raw_config: dict) -> dict:
        chat_id = str(raw_config.get("chat_id") or "").strip()
        if not chat_id:
            raise ValueError("chat_id is required")
        # chat_id 数字 (private chat) 或 @channelname
        if not (chat_id.lstrip("-").isdigit() or chat_id.startswith("@")):
            raise ValueError(
                "chat_id must be numeric (e.g. 123456) or @channel_username"
            )
        return {"chat_id": chat_id}

    @classmethod
    def public_view(cls, config: dict) -> dict:
        return {"chat_id": config.get("chat_id", "")}
