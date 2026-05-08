"""
LLM Prompt Cache — Redis-backed memoization for deterministic agent calls.

设计原则（B1）：
- 只对 temperature ≤ 0.4 的调用缓存（planning/scoring/extraction 都在 0~0.3）
- 高温调用（创意生成、多次采样）一律绕过，避免掩盖随机性
- 命中时合成 LLMResult(cost_usd=0, latency_ms=0, finish_reason="cache_hit")
- 故障静默：Redis 挂了仍能继续 LLM 调用，缓存只是加速层
- 统计 hits/misses 到 Redis，可通过 GET /api/llm/cache/stats 查询命中率

Cache key: sha256(provider|model|temperature|prompt)
TTL: 默认 2h，Round 级别调用通常在 TTL 内复用；可配置。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CACHE_PREFIX = "llm:cache:"
STATS_HIT_KEY = "llm:cache:stats:hits"
STATS_MISS_KEY = "llm:cache:stats:misses"
CACHE_TEMP_THRESHOLD = 0.4
DEFAULT_TTL_SECONDS = 2 * 3600


def _rf_tag(response_format: Optional[Dict[str, Any]]) -> str:
    """JSON mode 与普通 text mode 的同一 prompt 结果不同，必须作为 cache key 的一维。"""
    if not response_format:
        return "text"
    return str(response_format.get("type", "text"))


def _make_key(
    prompt: str, temperature: float, provider: str, model: str,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    payload = f"{provider}|{model}|{temperature:.3f}|{_rf_tag(response_format)}|{prompt}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{CACHE_PREFIX}{digest}"


def should_cache(temperature: float) -> bool:
    """只缓存低温度（接近确定性）调用。配合 settings.enable_llm_cache 总开关。"""
    from app.config import settings
    if not getattr(settings, "enable_llm_cache", True):
        return False
    return temperature <= CACHE_TEMP_THRESHOLD


async def try_get_cached(
    prompt: str, temperature: float, provider: str, model: str,
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """缓存命中返回文本；miss / Redis 故障返回 None。"""
    if not should_cache(temperature):
        return None
    try:
        import redis.asyncio as aioredis
        from app.config import settings
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            key = _make_key(prompt, temperature, provider, model, response_format)
            val = await r.get(key)
            if val is not None:
                await r.incr(STATS_HIT_KEY)
                logger.info(
                    "[LLM-cache] HIT provider=%s model=%s prompt_len=%d",
                    provider, model, len(prompt),
                )
            else:
                await r.incr(STATS_MISS_KEY)
            return val
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug("[LLM-cache] lookup failed (benign): %s", e)
        return None


async def set_cached(
    prompt: str, temperature: float, provider: str, model: str,
    text: str, ttl_seconds: int = DEFAULT_TTL_SECONDS,
    response_format: Optional[Dict[str, Any]] = None,
) -> None:
    """写入缓存。空文本 / 缓存禁用时跳过。"""
    if not should_cache(temperature) or not text:
        return
    try:
        import redis.asyncio as aioredis
        from app.config import settings
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            key = _make_key(prompt, temperature, provider, model, response_format)
            await r.setex(key, ttl_seconds, text)
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug("[LLM-cache] store failed (benign): %s", e)


async def get_stats() -> dict:
    """返回 {hits, misses, hit_rate}。可供 /api/llm/cache/stats 暴露给 DevTools。"""
    try:
        import redis.asyncio as aioredis
        from app.config import settings
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            hits = int(await r.get(STATS_HIT_KEY) or 0)
            misses = int(await r.get(STATS_MISS_KEY) or 0)
            total = hits + misses
            return {
                "hits": hits,
                "misses": misses,
                "total": total,
                "hit_rate": round(hits / total, 4) if total else 0.0,
            }
        finally:
            await r.aclose()
    except Exception as e:
        return {"error": str(e), "hits": 0, "misses": 0, "hit_rate": 0.0}


async def reset_stats() -> None:
    """仅 DevTools/测试用。生产不会调用。"""
    try:
        import redis.asyncio as aioredis
        from app.config import settings
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.delete(STATS_HIT_KEY, STATS_MISS_KEY)
        finally:
            await r.aclose()
    except Exception:
        pass
