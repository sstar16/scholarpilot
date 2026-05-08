"""飞书群机器人 channel — webhook URL POST JSON。

config_json:
    {"webhook_url_enc": "<encrypted>"}

API: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
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
from app.services.notifications.crypto import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)

logger = logging.getLogger(__name__)


_FEISHU_HOST_PREFIXES = (
    "https://open.feishu.cn/open-apis/bot/v2/hook/",
    "https://open.larksuite.com/open-apis/bot/v2/hook/",
)


class FeishuChannel(NotificationChannel):
    channel_id: ClassVar[str] = "feishu"
    display_name: ClassVar[str] = "飞书群机器人"
    config_kind: ClassVar[str] = "webhook"

    async def send(
        self, config: dict, payload: NotificationPayload,
    ) -> NotificationResult:
        try:
            webhook = decrypt_secret(config.get("webhook_url_enc", ""))
        except ValueError as e:
            return NotificationResult(self.channel_id, False, f"config decrypt failed: {e}")
        if not webhook:
            return NotificationResult(self.channel_id, False, "webhook_url empty")

        text_lines = [payload.title, "", payload.body]
        if payload.links:
            text_lines.append("")
            for label, url in payload.links:
                text_lines.append(f"{label}: {url}")
        text = "\n".join(text_lines)

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": settings.notification_user_agent},
            ) as client:
                resp = await client.post(
                    webhook,
                    json={"msg_type": "text", "content": {"text": text}},
                )
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
        # 飞书 V2 webhook 成功 code=0；旧版 StatusCode=0
        if body.get("code") == 0 or body.get("StatusCode") == 0:
            return NotificationResult(self.channel_id, True, "ok")
        return NotificationResult(
            self.channel_id, False,
            f"api error: {body.get('msg') or body.get('StatusMessage') or body}",
            response_body=str(body)[:200],
        )

    @classmethod
    def validate_config(cls, raw_config: dict) -> dict:
        webhook = (raw_config.get("webhook_url") or "").strip()
        if not webhook:
            raise ValueError("webhook_url is required")
        if not any(webhook.startswith(p) for p in _FEISHU_HOST_PREFIXES):
            raise ValueError(
                "webhook_url must start with https://open.feishu.cn/... or https://open.larksuite.com/..."
            )
        return {"webhook_url_enc": encrypt_secret(webhook)}

    @classmethod
    def public_view(cls, config: dict) -> dict:
        try:
            webhook = decrypt_secret(config.get("webhook_url_enc", ""))
        except ValueError:
            return {"webhook_url_masked": "(decrypt failed)"}
        return {"webhook_url_masked": mask_secret(webhook, keep_head=30, keep_tail=8)}
