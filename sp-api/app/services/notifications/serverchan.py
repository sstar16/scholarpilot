"""微信 Server酱（Server酱·Turbo）channel。

用户在 https://sct.ftqq.com 绑定微信 → 拿 SendKey（如 SCT123456abcdef）→
POST https://sctapi.ftqq.com/<SCKEY>.send 转推到用户微信。

config_json:
    {"send_key_enc": "<encrypted>"}

免费版 5 条/d；¥18/年付费版无限。
"""
from __future__ import annotations

import asyncio
import logging
import re
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

# Server酱 SendKey 通常以 SCT 开头 + 字母数字（无固定长度公布，宽松校验）
_SCT_KEY_RE = re.compile(r"^SCT[A-Za-z0-9_-]{6,}$")


class ServerChanChannel(NotificationChannel):
    channel_id: ClassVar[str] = "serverchan"
    display_name: ClassVar[str] = "微信 Server酱"
    config_kind: ClassVar[str] = "webhook"

    async def send(
        self, config: dict, payload: NotificationPayload,
    ) -> NotificationResult:
        try:
            send_key = decrypt_secret(config.get("send_key_enc", ""))
        except ValueError as e:
            return NotificationResult(self.channel_id, False, f"config decrypt failed: {e}")
        if not send_key:
            return NotificationResult(self.channel_id, False, "send_key empty")

        # title 30 字内；desp markdown 32KB 内（Server酱限制）
        title = payload.title[:30]
        desp_lines = [payload.body]
        if payload.links:
            desp_lines.append("")
            for label, url in payload.links:
                desp_lines.append(f"- [{label}]({url})")
        desp = "\n".join(desp_lines)[:32_000]

        url = f"https://sctapi.ftqq.com/{send_key}.send"
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": settings.notification_user_agent},
            ) as client:
                resp = await client.post(url, data={"title": title, "desp": desp})
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
        # Server酱 API: code=0 success, code!=0 failed
        if body.get("code") == 0:
            return NotificationResult(self.channel_id, True, "ok")
        return NotificationResult(
            self.channel_id, False,
            f"api error: {body.get('message')}",
            response_body=str(body)[:200],
        )

    @classmethod
    def validate_config(cls, raw_config: dict) -> dict:
        send_key = (raw_config.get("send_key") or "").strip()
        if not send_key:
            raise ValueError("send_key is required")
        if not _SCT_KEY_RE.match(send_key):
            raise ValueError("send_key format invalid (expected SCTxxxxxx)")
        return {"send_key_enc": encrypt_secret(send_key)}

    @classmethod
    def public_view(cls, config: dict) -> dict:
        try:
            key = decrypt_secret(config.get("send_key_enc", ""))
        except ValueError:
            return {"send_key_masked": "(decrypt failed)"}
        return {"send_key_masked": mask_secret(key, keep_head=4, keep_tail=4)}
