"""
数据源运行时配置：Redis 持久化 + 进程级单例缓存

模式复用自 llm_config_store.py：
- 进程级单例 + 60s Redis TTL 缓存
- save 后同进程立即生效，其他进程靠 TTL 过期刷新
- 存储内容：运行时禁用覆盖 + 凭证覆盖
"""
import asyncio
import json
import os
import time
from typing import Dict, Optional, Set

REDIS_KEY = "sources:config"
CACHE_TTL = 60.0

# 每个源需要的凭证 key（仅列出需要凭证的源）
SOURCE_CREDENTIALS: Dict[str, list] = {
    "semantic_scholar": ["SEMANTIC_SCHOLAR_API_KEY"],
    "epo_ops": ["EPO_CONSUMER_KEY", "EPO_CONSUMER_SECRET"],
    "lens_patent": ["LENS_API_TOKEN"],
    "bigquery_patents": ["GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CREDENTIALS_JSON"],
    "patenthub": ["PATENTHUB_API_TOKEN"],
}

# ── 进程级缓存 ──
_config: Optional[dict] = None
_loaded_at: float = 0.0
_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_source_config() -> dict:
    """获取源配置（单例 + TTL 缓存）。"""
    global _config, _loaded_at

    now = time.monotonic()
    if _config is not None and (now - _loaded_at) < CACHE_TTL:
        return _config

    async with _get_lock():
        now = time.monotonic()
        if _config is not None and (now - _loaded_at) < CACHE_TTL:
            return _config

        _config = await _load_from_redis()
        _loaded_at = time.monotonic()

    return _config


async def save_source_config(config: dict) -> None:
    """持久化到 Redis 并刷新本地缓存。"""
    global _config, _loaded_at

    import redis.asyncio as aioredis
    from app.config import settings

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.set(REDIS_KEY, json.dumps(config, ensure_ascii=False))
    finally:
        await r.aclose()

    _config = config
    _loaded_at = time.monotonic()


async def get_effective_disabled() -> Set[str]:
    """合并 env DISABLED_SOURCES + Redis 覆盖。enabled_overrides 可反转 env 禁用。"""
    env_disabled = {
        s.strip()
        for s in os.getenv("DISABLED_SOURCES", "").split(",")
        if s.strip()
    }
    config = await get_source_config()
    runtime_disabled = set(config.get("disabled_overrides", []))
    runtime_enabled = set(config.get("enabled_overrides", []))
    return (env_disabled | runtime_disabled) - runtime_enabled


async def get_credential(source_id: str, key: str) -> str:
    """获取凭证：Redis 覆盖优先，回退 os.getenv。"""
    config = await get_source_config()
    overrides = config.get("credential_overrides", {}).get(source_id, {})
    if key in overrides and overrides[key]:
        return overrides[key]
    return os.getenv(key, "")


def get_proxy_for_source(source_id: str) -> Optional[str]:
    """同步获取代理 URL：per-source 覆盖 > global_proxy > env FETCH_PROXY。从缓存读取。"""
    if _config:
        proxy = _config.get("proxy_overrides", {}).get(source_id)
        if proxy:
            return proxy
        global_proxy = _config.get("global_proxy")
        if global_proxy:
            return global_proxy
    return os.getenv("FETCH_PROXY", "") or None


def mask_value(value: str) -> str:
    """脱敏显示：仅保留末 4 位。"""
    if not value or len(value) <= 4:
        return "****"
    return "****" + value[-4:]


# ── 内部 ──

async def _load_from_redis() -> dict:
    import redis.asyncio as aioredis
    from app.config import settings

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        data = await r.get(REDIS_KEY)
        if data:
            return json.loads(data)
        return {"disabled_overrides": [], "credential_overrides": {}}
    except Exception:
        return {"disabled_overrides": [], "credential_overrides": {}}
    finally:
        await r.aclose()
