"""邮件通道（SMTP）— stdlib smtplib + email.mime，零新增 deps。

config_json:
    {
      "address": "user@example.com",
      # 可选：用户自定 SMTP（不填则用 settings.smtp_*）
      "smtp_host": "smtp.qq.com",       # optional
      "smtp_port": 465,                 # optional
      "smtp_user": "...",               # optional
      "smtp_password_enc": "<enc>",     # optional, 加密
      "smtp_use_tls": true,             # optional
      "from_address": "...",            # optional
    }

平台默认 SMTP（settings.smtp_*）适用于多数用户；高级用户可填自家 SMTP。
"""
from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import ClassVar

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

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _render_html(payload: NotificationPayload) -> str:
    safe_title = (payload.title or "").replace("<", "&lt;").replace(">", "&gt;")
    body_html = (payload.body or "").replace("\n", "<br/>").replace(
        "<", "&lt;").replace(">", "&gt;")
    links_html = ""
    if payload.links:
        items = "".join(
            f'<li><a href="{u}">{lbl}</a></li>'
            for lbl, u in payload.links
        )
        links_html = f"<ul>{items}</ul>"
    return (
        f"<html><body>"
        f"<h2>{safe_title}</h2>"
        f"<p>{body_html}</p>"
        f"{links_html}"
        f"<hr/>"
        f"<p style='color:#999;font-size:12px'>"
        f"由 ScholarPilot 自动发送 — 取消推送请到客户端 Settings · 通知。"
        f"</p>"
        f"</body></html>"
    )


def _resolve_smtp(user_cfg: dict) -> dict:
    """合并用户级 SMTP 配置 + 平台默认。返回最终连接参数。"""
    out = {
        "host": user_cfg.get("smtp_host") or settings.smtp_host,
        "port": int(user_cfg.get("smtp_port") or settings.smtp_port or 587),
        "user": user_cfg.get("smtp_user") or settings.smtp_user,
        "use_tls": (
            user_cfg.get("smtp_use_tls")
            if "smtp_use_tls" in user_cfg
            else settings.smtp_use_tls
        ),
        "from_address": (
            user_cfg.get("from_address")
            or settings.smtp_from_address
            or settings.smtp_user
        ),
        "from_name": settings.smtp_from_name or "ScholarPilot",
    }
    # password：用户加密 > 平台默认
    user_pw_enc = user_cfg.get("smtp_password_enc")
    if user_pw_enc:
        try:
            out["password"] = decrypt_secret(user_pw_enc)
        except ValueError:
            out["password"] = ""
    else:
        out["password"] = settings.smtp_password
    return out


def _send_smtp_blocking(smtp: dict, to_address: str, subject: str, html_body: str) -> None:
    """阻塞的 smtplib 调用，run_in_executor 包装。失败抛异常。"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{smtp['from_name']} <{smtp['from_address']}>"
    msg["To"] = to_address
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if smtp["port"] == 465:
        # SSL 模式
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp["host"], smtp["port"], context=ctx, timeout=15) as s:
            if smtp["user"] and smtp["password"]:
                s.login(smtp["user"], smtp["password"])
            s.sendmail(smtp["from_address"], [to_address], msg.as_string())
    else:
        # STARTTLS / 明文
        with smtplib.SMTP(smtp["host"], smtp["port"], timeout=15) as s:
            s.ehlo()
            if smtp["use_tls"]:
                ctx = ssl.create_default_context()
                s.starttls(context=ctx)
                s.ehlo()
            if smtp["user"] and smtp["password"]:
                s.login(smtp["user"], smtp["password"])
            s.sendmail(smtp["from_address"], [to_address], msg.as_string())


class EmailChannel(NotificationChannel):
    channel_id: ClassVar[str] = "email"
    display_name: ClassVar[str] = "邮件"
    config_kind: ClassVar[str] = "email"

    async def send(
        self, config: dict, payload: NotificationPayload,
    ) -> NotificationResult:
        to_address = (config.get("address") or "").strip()
        if not _EMAIL_RE.match(to_address):
            return NotificationResult(self.channel_id, False, "invalid recipient address")

        smtp = _resolve_smtp(config)
        if not smtp["host"]:
            return NotificationResult(
                self.channel_id, False,
                "no SMTP host configured (set SMTP_HOST or user SMTP)",
            )

        subject = payload.title[:200]
        html = _render_html(payload)

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, _send_smtp_blocking, smtp, to_address, subject, html,
            )
        except smtplib.SMTPAuthenticationError as e:
            return NotificationResult(self.channel_id, False, f"smtp auth failed: {e}")
        except smtplib.SMTPException as e:
            return NotificationResult(self.channel_id, False, f"smtp error: {e}")
        except (OSError, asyncio.TimeoutError) as e:
            return NotificationResult(self.channel_id, False, f"network error: {e}")
        except Exception as e:
            return NotificationResult(self.channel_id, False, f"unexpected: {e}")

        return NotificationResult(self.channel_id, True, "ok")

    @classmethod
    def validate_config(cls, raw_config: dict) -> dict:
        address = (raw_config.get("address") or "").strip()
        if not _EMAIL_RE.match(address):
            raise ValueError("address must be a valid email")
        out: dict = {"address": address}

        smtp_host = (raw_config.get("smtp_host") or "").strip()
        if smtp_host:
            out["smtp_host"] = smtp_host
            try:
                out["smtp_port"] = int(raw_config.get("smtp_port") or 587)
            except (TypeError, ValueError):
                raise ValueError("smtp_port must be int")
            out["smtp_user"] = (raw_config.get("smtp_user") or "").strip()
            pw = (raw_config.get("smtp_password") or "").strip()
            if pw:
                out["smtp_password_enc"] = encrypt_secret(pw)
            if "smtp_use_tls" in raw_config:
                out["smtp_use_tls"] = bool(raw_config["smtp_use_tls"])
            from_addr = (raw_config.get("from_address") or "").strip()
            if from_addr:
                if not _EMAIL_RE.match(from_addr):
                    raise ValueError("from_address must be a valid email")
                out["from_address"] = from_addr
        return out

    @classmethod
    def public_view(cls, config: dict) -> dict:
        view: dict = {"address": config.get("address", "")}
        if "smtp_host" in config:
            view["smtp_host"] = config["smtp_host"]
            view["smtp_port"] = config.get("smtp_port", 587)
            view["smtp_user"] = config.get("smtp_user", "")
            view["smtp_use_tls"] = config.get("smtp_use_tls", True)
            view["from_address"] = config.get("from_address", "")
            # 密码不展示，只标记是否设置
            view["smtp_password_set"] = bool(config.get("smtp_password_enc"))
        else:
            view["uses_platform_smtp"] = True
        return view
