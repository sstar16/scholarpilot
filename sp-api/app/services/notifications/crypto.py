"""敏感字段对称加密（webhook URL / send_key / smtp_password）。

cryptography.Fernet（python-jose 已带 cryptography deps，零新增）。

key 取值：
  - 生产：settings.notification_secret = base64(32 random bytes)，通过 .env
  - 开发：notification_secret 留空时，从 settings.secret_key 派生（sha256 → b64）
    ↑ 这是显式的 dev 行为，不是“静默 fallback”：如果生产忘配 NOTIFICATION_SECRET 就等于
    用 SECRET_KEY 当对称密钥；这个 trade-off 是可接受的，因为 SECRET_KEY 本身保密。

加解密失败抛 ValueError（不静默），让 admin 看到真实问题。
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _derive_fernet_key(material: str) -> bytes:
    """从任意字符串派生合法 Fernet key（32 字节 base64）。"""
    raw = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(raw)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    raw = (settings.notification_secret or "").strip()
    if raw:
        try:
            # 期望是 Fernet 直接可用的 base64 32B key
            return Fernet(raw.encode("utf-8"))
        except (ValueError, Exception):
            # 用户配的是普通字符串而非 Fernet key → 派生
            return Fernet(_derive_fernet_key(raw))
    # 未配 → 从 SECRET_KEY 派生（dev 默认）
    return Fernet(_derive_fernet_key(settings.secret_key))


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted: str) -> str:
    if not encrypted:
        return ""
    try:
        return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "Encrypted secret invalid (key rotation? db corruption?)"
        ) from e


def mask_secret(plaintext: str, *, keep_head: int = 6, keep_tail: int = 4) -> str:
    """脱敏展示给前端。'https://hooks.feishu.cn/xxx' → 'https:***...cdef'"""
    if not plaintext:
        return ""
    if len(plaintext) <= keep_head + keep_tail + 3:
        return "***"
    return f"{plaintext[:keep_head]}***{plaintext[-keep_tail:]}"
