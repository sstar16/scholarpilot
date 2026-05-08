"""飞书（Lark）机器人通知 —— 推送用户反馈到飞书群（site_feedback 用）。"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


_CATEGORY_EMOJI = {
    "bug": "🐞",
    "suggestion": "💡",
    "praise": "❤️",
    "other": "📝",
}


async def send_feedback_notification(
    *,
    feedback_id: str,
    category: str,
    content: str,
    user_email: Optional[str] = None,
    contact: Optional[str] = None,
    page_url: Optional[str] = None,
) -> bool:
    """推送反馈到飞书群。返回是否成功；失败只打 warning，不抛。"""
    webhook = (settings.feishu_webhook_url or "").strip()
    if not webhook:
        logger.info("[feishu] 未配置 webhook，跳过通知")
        return False

    emoji = _CATEGORY_EMOJI.get(category, "📝")
    category_label = {
        "bug": "Bug 报告",
        "suggestion": "功能建议",
        "praise": "好评",
        "other": "其他",
    }.get(category, category)

    content_truncated = content.strip()
    if len(content_truncated) > 1500:
        content_truncated = content_truncated[:1500] + "…"

    lines = [
        f"{emoji} ScholarPilot 新反馈",
        f"分类：{category_label}",
        f"用户：{user_email or '(匿名)'}",
    ]
    if contact:
        lines.append(f"联系：{contact}")
    if page_url:
        lines.append(f"页面：{page_url}")
    lines.append("————————————")
    lines.append(content_truncated)
    lines.append("————————————")
    lines.append(f"id={feedback_id[:8]}")

    text = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(webhook, json={
                "msg_type": "text",
                "content": {"text": text},
            })
        if resp.status_code == 200:
            body = resp.json()
            if body.get("code") == 0 or body.get("StatusCode") == 0:
                logger.info("[feishu] 反馈通知已发送 id=%s", feedback_id[:8])
                return True
            logger.warning("[feishu] API 返回错误 body=%s", body)
            return False
        logger.warning(
            "[feishu] 发送失败 status=%s body=%s",
            resp.status_code, resp.text[:200],
        )
        return False
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.warning("[feishu] 无法连接 %s: %s", webhook[:60], e)
        return False
    except asyncio.TimeoutError:
        logger.warning("[feishu] 发送超时")
        return False
    except Exception as e:
        logger.warning("[feishu] 发送异常: %s", e)
        return False
