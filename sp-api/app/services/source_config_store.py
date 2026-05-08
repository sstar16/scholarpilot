"""数据源运行时配置 — sp-api 简化版（无 DevTools UI 写入路径）。

vs backend/app/services/source_config_store.py：
- 仅保留只读读取路径（fetcher 调用 get_credential / get_proxy_for_source）
- env DISABLED_SOURCES 直读（无 Redis 覆盖）
- 写路径未挂出来：sp-api 不带 DevTools sources UI；运行时禁用全靠环境变量重启生效
"""
import json
import os
import time
from typing import Optional, Set


REDIS_KEY = "sources:config"
CACHE_TTL = 60.0

# 进程级缓存
_config: Optional[dict] = None
_loaded_at: float = 0.0


async def _load_from_redis() -> dict:
    import redis.asyncio as aioredis
    from app.config import settings

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        data = await r.get(REDIS_KEY)
        if data:
            return json.loads(data)
        return {"disabled_overrides": [], "credential_overrides": {}, "proxy_overrides": {}}
    except Exception:
        return {"disabled_overrides": [], "credential_overrides": {}, "proxy_overrides": {}}
    finally:
        await r.aclose()


async def get_source_config() -> dict:
    """读源配置（单例 + TTL 缓存）。空 redis 也安全。"""
    global _config, _loaded_at
    now = time.monotonic()
    if _config is not None and (now - _loaded_at) < CACHE_TTL:
        return _config
    _config = await _load_from_redis()
    _loaded_at = time.monotonic()
    return _config


async def get_effective_disabled() -> Set[str]:
    """env DISABLED_SOURCES + Redis 覆盖；enabled_overrides 可反转 env 禁用。"""
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
    """凭证：Redis 覆盖优先，回退 os.getenv。"""
    config = await get_source_config()
    overrides = config.get("credential_overrides", {}).get(source_id, {})
    if key in overrides and overrides[key]:
        return overrides[key]
    return os.getenv(key, "")


def get_proxy_for_source(source_id: str) -> Optional[str]:
    """同步获取代理 URL（fetcher base.py _build_client 用）。无 Redis 缓存时退到 env。"""
    if _config:
        proxy = _config.get("proxy_overrides", {}).get(source_id)
        if proxy:
            return proxy
        global_proxy = _config.get("global_proxy")
        if global_proxy:
            return global_proxy
    return os.getenv("FETCH_PROXY", "") or None
