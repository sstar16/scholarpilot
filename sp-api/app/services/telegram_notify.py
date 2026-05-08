"""
Telegram 通知 —— 推送用户反馈到管理员 Telegram 账号。

配置缺失 / 网络错误 / 超时 → 静默降级，不影响主流程（反馈仍成功写入 DB）。
国内服务器部署时 api.telegram.org 可能被墙，用户可清空 TELEGRAM_BOT_TOKEN 关闭通知。
"""
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


def _escape_html(text: str) -> str:
    """Telegram HTML parse_mode 要求 <, >, & 转义"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def send_feedback_notification(
    *,
    feedback_id: str,
    category: str,
    content: str,
    user_email: Optional[str] = None,
    contact: Optional[str] = None,
    page_url: Optional[str] = None,
    admin_page_url: Optional[str] = None,
) -> bool:
    """
    推送反馈到 Telegram。返回是否成功；失败只打 warning，不抛。
    """
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not token or not chat_id:
        logger.info("[telegram] 未配置 token/chat_id，跳过通知")
        return False

    emoji = _CATEGORY_EMOJI.get(category, "📝")
    category_label = {
        "bug": "Bug 报告",
        "suggestion": "功能建议",
        "praise": "好评",
        "other": "其他",
    }.get(category, category)

    # 限长 + HTML 转义
    content_safe = _escape_html(content.strip())
    if len(content_safe) > 1500:
        content_safe = content_safe[:1500] + "…"

    lines = [
        f"{emoji} <b>ScholarPilot 新反馈</b>",
        f"<b>分类</b>：{_escape_html(category_label)}",
    ]
    if user_email:
        lines.append(f"<b>用户</b>：{_escape_html(user_email)}")
    else:
        lines.append("<b>用户</b>：(匿名)")
    if contact:
        lines.append(f"<b>联系</b>：{_escape_html(contact)}")
    if page_url:
        lines.append(f"<b>页面</b>：{_escape_html(page_url)}")
    lines.append("━━━━━━━━━━━━")
    lines.append(content_safe)
    lines.append("━━━━━━━━━━━━")
    lines.append(f"<code>id={feedback_id[:8]}</code>")
    if admin_page_url:
        lines.append(f'👉 <a href="{_escape_html(admin_page_url)}">查看/处理</a>')

    message = "\n".join(lines)
    # api_base 默认 https://api.telegram.org；国内服务器可配 Cloudflare Worker 反代 URL
    api_base = (settings.telegram_api_base or "https://api.telegram.org").rstrip("/")
    url = f"{api_base}/bot{token}/sendMessage"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info("[telegram] 反馈通知已发送 id=%s", feedback_id[:8])
            return True
        logger.warning(
            "[telegram] 发送失败 status=%s body=%s",
            resp.status_code, resp.text[:200],
        )
        return False
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.warning("[telegram] 无法连接 %s（可能被墙或 Worker 反代不通）: %s", api_base, e)
        return False
    except asyncio.TimeoutError:
        logger.warning("[telegram] 发送超时")
        return False
    except Exception as e:
        logger.warning("[telegram] 发送异常: %s", e)
        return False
