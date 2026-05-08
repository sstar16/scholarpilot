"""Notification channels tests — 不真发外部 HTTP / SMTP，全 mock。

覆盖：
  - registry：list_channels / get_channel
  - validate_config：合法 / 非法 raw_config
  - public_view：脱敏字段
  - crypto：encrypt/decrypt 往返 + mask
  - dispatcher：mock channel.send，验证 fan-out + 容错
  - HTTP channels：用 respx mock httpx 验证请求结构
  - email channel：用 patch smtplib.SMTP 验证调用
  - API：404/401 鉴权 + invalid input
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.notifications.base import NotificationPayload, NotificationResult
from app.services.notifications.crypto import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.notifications.email import EmailChannel
from app.services.notifications.feishu import FeishuChannel
from app.services.notifications.registry import get_channel, list_channels
from app.services.notifications.serverchan import ServerChanChannel
from app.services.notifications.telegram import TelegramChannel


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


# ─── registry ─────────────────────────────────────────────


def test_registry_lists_v1_channels():
    chs = list_channels()
    ids = {c["channel_id"] for c in chs}
    # V1 必须有这 4 个
    assert {"feishu", "serverchan", "email", "telegram"} <= ids


def test_get_channel_known():
    assert isinstance(get_channel("feishu"), FeishuChannel)
    assert isinstance(get_channel("serverchan"), ServerChanChannel)
    assert isinstance(get_channel("email"), EmailChannel)
    assert isinstance(get_channel("telegram"), TelegramChannel)


def test_get_channel_unknown():
    assert get_channel("xxxnonexistent") is None


# ─── crypto ───────────────────────────────────────────────


def test_crypto_encrypt_decrypt_roundtrip():
    plain = "https://hooks.feishu.cn/super-secret-token"
    enc = encrypt_secret(plain)
    assert enc and enc != plain
    assert decrypt_secret(enc) == plain


def test_crypto_empty_string():
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""


def test_crypto_decrypt_invalid_raises():
    with pytest.raises(ValueError):
        decrypt_secret("garbage-not-fernet-token")


def test_crypto_mask():
    assert mask_secret("") == ""
    assert mask_secret("short") == "***"
    masked = mask_secret("https://hooks.feishu.cn/abcdef-very-long-url", keep_head=10, keep_tail=4)
    assert masked.startswith("https://ho")
    assert masked.endswith("-url")
    assert "***" in masked


# ─── validate_config ──────────────────────────────────────


def test_feishu_validate_ok():
    out = FeishuChannel.validate_config(
        {"webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc123"}
    )
    assert "webhook_url_enc" in out
    # 加密往返
    assert decrypt_secret(out["webhook_url_enc"]).startswith("https://open.feishu.cn")


def test_feishu_validate_rejects_invalid_host():
    with pytest.raises(ValueError):
        FeishuChannel.validate_config({"webhook_url": "https://evil.example.com/x"})


def test_feishu_validate_rejects_empty():
    with pytest.raises(ValueError):
        FeishuChannel.validate_config({})


def test_serverchan_validate_ok():
    out = ServerChanChannel.validate_config({"send_key": "SCT123abcdef"})
    assert "send_key_enc" in out


def test_serverchan_validate_rejects_bad_format():
    with pytest.raises(ValueError):
        ServerChanChannel.validate_config({"send_key": "not-a-sct-key"})


def test_email_validate_ok_minimal():
    out = EmailChannel.validate_config({"address": "user@example.com"})
    assert out["address"] == "user@example.com"
    assert "smtp_host" not in out  # 用平台默认


def test_email_validate_ok_with_user_smtp():
    out = EmailChannel.validate_config({
        "address": "u@a.com",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "smtp_user": "u@a.com",
        "smtp_password": "secret",
        "from_address": "u@a.com",
    })
    assert out["smtp_host"] == "smtp.qq.com"
    assert out["smtp_port"] == 465
    assert "smtp_password_enc" in out
    assert decrypt_secret(out["smtp_password_enc"]) == "secret"


def test_email_validate_rejects_bad_email():
    with pytest.raises(ValueError):
        EmailChannel.validate_config({"address": "not-an-email"})


def test_telegram_validate_ok_numeric():
    out = TelegramChannel.validate_config({"chat_id": "123456"})
    assert out["chat_id"] == "123456"


def test_telegram_validate_ok_negative():
    """群组 chat_id 是负数。"""
    out = TelegramChannel.validate_config({"chat_id": "-1001234567"})
    assert out["chat_id"] == "-1001234567"


def test_telegram_validate_ok_channel():
    out = TelegramChannel.validate_config({"chat_id": "@my_channel"})
    assert out["chat_id"] == "@my_channel"


def test_telegram_validate_rejects_bad():
    with pytest.raises(ValueError):
        TelegramChannel.validate_config({"chat_id": "not_at_or_number"})


# ─── public_view ──────────────────────────────────────────


def test_feishu_public_view_masks_url():
    enc = encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/long-secret-token-x")
    view = FeishuChannel.public_view({"webhook_url_enc": enc})
    assert "webhook_url_masked" in view
    assert "***" in view["webhook_url_masked"]


def test_serverchan_public_view_masks_key():
    enc = encrypt_secret("SCT123abcdef")
    view = ServerChanChannel.public_view({"send_key_enc": enc})
    assert "***" in view["send_key_masked"]


def test_email_public_view_no_password():
    enc_pw = encrypt_secret("supersecret")
    view = EmailChannel.public_view({
        "address": "u@a.com",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "smtp_password_enc": enc_pw,
    })
    assert view["address"] == "u@a.com"
    assert "smtp_password_enc" not in view  # 加密的也不直接吐
    assert view["smtp_password_set"] is True


# ─── channel.send (mock httpx / smtplib) ───────────────────


@pytest.mark.asyncio
async def test_feishu_send_ok():
    enc = encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/x")
    config = {"webhook_url_enc": enc}
    payload = NotificationPayload(title="t", body="b")

    class FakeResp:
        status_code = 200
        text = '{"code":0}'
        def json(self): return {"code": 0}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return FakeResp()

    with patch("app.services.notifications.feishu.httpx.AsyncClient", FakeClient):
        ch = FeishuChannel()
        result = await ch.send(config, payload)
        assert result.ok
        assert result.channel == "feishu"


@pytest.mark.asyncio
async def test_feishu_send_http_error():
    enc = encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/x")
    config = {"webhook_url_enc": enc}
    payload = NotificationPayload(title="t", body="b")

    class FakeResp:
        status_code = 500
        text = "server error"
        def json(self): raise ValueError()

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return FakeResp()

    with patch("app.services.notifications.feishu.httpx.AsyncClient", FakeClient):
        ch = FeishuChannel()
        result = await ch.send(config, payload)
        assert not result.ok
        assert "HTTP 500" in result.message


@pytest.mark.asyncio
async def test_feishu_send_api_error_body():
    enc = encrypt_secret("https://open.feishu.cn/open-apis/bot/v2/hook/x")
    config = {"webhook_url_enc": enc}

    class FakeResp:
        status_code = 200
        text = '{"code":99,"msg":"bad sign"}'
        def json(self): return {"code": 99, "msg": "bad sign"}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return FakeResp()

    with patch("app.services.notifications.feishu.httpx.AsyncClient", FakeClient):
        result = await FeishuChannel().send(config, NotificationPayload(title="t", body="b"))
        assert not result.ok
        assert "bad sign" in result.message


@pytest.mark.asyncio
async def test_feishu_send_decrypt_failure():
    config = {"webhook_url_enc": "garbage"}
    result = await FeishuChannel().send(config, NotificationPayload(title="t", body="b"))
    assert not result.ok
    assert "decrypt failed" in result.message


@pytest.mark.asyncio
async def test_serverchan_send_ok():
    enc = encrypt_secret("SCT123abcdef")
    config = {"send_key_enc": enc}

    class FakeResp:
        status_code = 200
        text = '{"code":0}'
        def json(self): return {"code": 0}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return FakeResp()

    with patch("app.services.notifications.serverchan.httpx.AsyncClient", FakeClient):
        result = await ServerChanChannel().send(config, NotificationPayload(title="t", body="b"))
        assert result.ok


@pytest.mark.asyncio
async def test_telegram_send_no_platform_token(monkeypatch):
    """settings.telegram_bot_token 空时应直接返 ok=False。"""
    from app.services.notifications import telegram as tg_module
    monkeypatch.setattr(tg_module.settings, "telegram_bot_token", "")
    result = await TelegramChannel().send(
        {"chat_id": "123"}, NotificationPayload(title="t", body="b"),
    )
    assert not result.ok
    assert "telegram_bot_token" in result.message


@pytest.mark.asyncio
async def test_telegram_send_ok(monkeypatch):
    from app.services.notifications import telegram as tg_module
    monkeypatch.setattr(tg_module.settings, "telegram_bot_token", "fake-token")

    class FakeResp:
        status_code = 200
        text = '{"ok":true}'
        def json(self): return {"ok": True}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return FakeResp()

    with patch("app.services.notifications.telegram.httpx.AsyncClient", FakeClient):
        result = await TelegramChannel().send(
            {"chat_id": "123"}, NotificationPayload(title="t", body="b"),
        )
        assert result.ok


@pytest.mark.asyncio
async def test_email_send_ok():
    """patch smtplib.SMTP，验证 sendmail 被调。"""
    payload = NotificationPayload(title="t", body="b", links=[("查看", "https://x")])

    fake_smtp = MagicMock()
    fake_smtp.__enter__ = MagicMock(return_value=fake_smtp)
    fake_smtp.__exit__ = MagicMock(return_value=None)

    with patch("app.services.notifications.email.smtplib.SMTP", return_value=fake_smtp):
        # patch 平台 SMTP 配置
        with patch("app.services.notifications.email.settings") as fake_settings:
            fake_settings.smtp_host = "smtp.example.com"
            fake_settings.smtp_port = 587
            fake_settings.smtp_user = "noreply@example.com"
            fake_settings.smtp_password = "pw"
            fake_settings.smtp_use_tls = True
            fake_settings.smtp_from_address = "noreply@example.com"
            fake_settings.smtp_from_name = "ScholarPilot"

            result = await EmailChannel().send(
                {"address": "user@example.com"}, payload,
            )
            assert result.ok, result.message
            fake_smtp.sendmail.assert_called_once()


@pytest.mark.asyncio
async def test_email_send_no_smtp_host():
    """没配 SMTP host 直接返 fail。"""
    with patch("app.services.notifications.email.settings") as fake_settings:
        fake_settings.smtp_host = ""
        fake_settings.smtp_port = 587
        fake_settings.smtp_user = ""
        fake_settings.smtp_password = ""
        fake_settings.smtp_use_tls = True
        fake_settings.smtp_from_address = ""
        fake_settings.smtp_from_name = "ScholarPilot"

        result = await EmailChannel().send(
            {"address": "user@example.com"},
            NotificationPayload(title="t", body="b"),
        )
        assert not result.ok
        assert "SMTP" in result.message


@pytest.mark.asyncio
async def test_email_send_invalid_recipient():
    result = await EmailChannel().send(
        {"address": "not-an-email"},
        NotificationPayload(title="t", body="b"),
    )
    assert not result.ok
    assert "invalid recipient" in result.message


# ─── dispatcher ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_no_settings():
    """没有任何 user setting → 返回空列表。"""
    import uuid as uuid_mod
    # AsyncMock().execute 是 awaitable；其 return_value 应是同步 mock（result.scalars().all()）
    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = []
    fake_db = AsyncMock()
    fake_db.execute.return_value = fake_result
    results = await NotificationDispatcher.dispatch(
        db=fake_db, user_id=uuid_mod.uuid4(),
        payload=NotificationPayload(title="t", body="b"),
    )
    assert results == []


@pytest.mark.asyncio
async def test_dispatcher_unknown_channel_in_db():
    """DB 里 channel='xxx' 但没注册 → 该 row 失败，不影响其他。"""
    import uuid as uuid_mod
    from app.models.user_notification_setting import UserNotificationSetting

    row_bad = UserNotificationSetting(
        user_id=uuid_mod.uuid4(),
        channel="xxx_unknown",
        config_json={},
        is_active=True,
    )

    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = [row_bad]
    fake_db = AsyncMock()
    fake_db.execute.return_value = fake_result

    results = await NotificationDispatcher.dispatch(
        db=fake_db, user_id=row_bad.user_id,
        payload=NotificationPayload(title="t", body="b"),
    )
    assert len(results) == 1
    assert not results[0].ok
    assert "not registered" in results[0].message


@pytest.mark.asyncio
async def test_dispatcher_test_channel_unknown():
    """test_channel 对未知 channel_id 返 ok=False。"""
    result = await NotificationDispatcher.test_channel(
        channel_id="xxxnonexistent",
        config={},
        payload=NotificationPayload(title="t", body="b"),
    )
    assert not result.ok
    assert "unknown" in result.message


# ─── API rookie / auth ────────────────────────────────────


def test_api_list_channels_needs_auth():
    c = _client()
    r = c.get("/api/users/me/notifications/channels")
    assert r.status_code == 401


def test_api_list_settings_needs_auth():
    c = _client()
    r = c.get("/api/users/me/notifications")
    assert r.status_code == 401


def test_api_upsert_needs_auth():
    c = _client()
    r = c.post("/api/users/me/notifications", json={
        "channel": "feishu", "config": {},
    })
    assert r.status_code == 401


def test_api_test_send_needs_auth():
    c = _client()
    r = c.post("/api/users/me/notifications/test", json={
        "channel": "feishu", "config": {},
    })
    assert r.status_code == 401


def test_api_delete_needs_auth():
    c = _client()
    r = c.delete("/api/users/me/notifications/feishu")
    assert r.status_code == 401


def test_api_routes_count_grew():
    """V1 路由必须新增 6 个 notifications endpoint。"""
    from app.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    notif_paths = {p for p in paths if "/notifications" in p}
    # GET /channels, GET '', POST '', POST /toggle, DELETE, POST /test
    assert len(notif_paths) >= 5, f"expected 5+ notification routes, got: {notif_paths}"
