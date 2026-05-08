"""健康检查 / 数据源列表缓存。

/health 和 /api/health 每次都跑 FetcherRegistry.get_all_info()（Python dict 循环）。
100 并发健康检查 = 100 次循环。这里用 in-memory + Redis 双层缓存（5 min TTL）降低重复开销。
"""
import json
import time
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.services.fetchers.base import FetcherRegistry

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 分钟
_REDIS_KEY = "sp-api:health:sources"

# 进程内 L1 缓存（避免每次 Redis round-trip）
_local_cache: dict[str, Any] | None = None
_local_cache_at: float = 0.0


async def get_cached_sources() -> list[dict[str, Any]]:
    """返回 FetcherRegistry.get_all_info() 的缓存结果（L1 内存 → L2 Redis → 直接计算）。"""
    global _local_cache, _local_cache_at

    now = time.monotonic()

    # L1：进程内缓存
    if _local_cache is not None and (now - _local_cache_at) < _CACHE_TTL:
        return _local_cache

    # L2：Redis 缓存
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        async with r:
            raw = await r.get(_REDIS_KEY)
            if raw:
                data: list[dict[str, Any]] = json.loads(raw)
                _local_cache = data
                _local_cache_at = now
                return data
    except Exception:
        logger.debug("health_cache: Redis 不可达，直接计算", exc_info=True)

    # Fallback：直接计算并写入缓存
    data = FetcherRegistry.get_all_info()
    _local_cache = data
    _local_cache_at = now

    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        async with r:
            await r.set(_REDIS_KEY, json.dumps(data), ex=_CACHE_TTL)
    except Exception:
        logger.debug("health_cache: 写 Redis 失败，仅用内存缓存", exc_info=True)

    return data
