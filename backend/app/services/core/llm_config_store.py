"""
LLM 提供商配置：Redis 持久化 + 进程级单例缓存

所有代码通过 `await get_llm_manager()` 获取 LLM 管理器，
不再手动实例化 LLMProviderManager。

- FastAPI 进程：共享同一个 manager 实例
- Celery worker 进程：每个 fork 拥有独立实例（模块级全局变量 copy-on-write）
- Redis 缓存 TTL 60s：避免每次 LLM 调用都读 Redis
- save 后自动 invalidate 同进程缓存，其他进程靠 TTL 过期刷新
"""
import asyncio
import json
import time

REDIS_KEY = "llm:config"
CACHE_TTL_SECONDS = 60.0

# ── 进程级缓存 ──
_manager = None          # LLMProviderManager 单例
_loaded_at: float = 0.0  # monotonic 时间戳
_refresh_lock: asyncio.Lock | None = None  # 防并发 refresh


def _get_lock() -> asyncio.Lock:
    """懒创建 asyncio.Lock（每个事件循环一个）"""
    global _refresh_lock
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    return _refresh_lock


async def get_llm_manager():
    """
    获取 LLM 管理器单例（唯一公共入口）。

    首次调用：创建实例 + 从 Redis 加载配置。
    TTL 内：直接返回缓存实例，零 Redis 开销。
    TTL 过期：从 Redis 刷新到同一实例（in-place）。
    """
    global _manager, _loaded_at

    now = time.monotonic()

    # 快速路径：缓存命中
    if _manager is not None and (now - _loaded_at) < CACHE_TTL_SECONDS:
        return _manager

    async with _get_lock():
        # double-check：另一个协程可能刚刷新过
        now = time.monotonic()
        if _manager is not None and (now - _loaded_at) < CACHE_TTL_SECONDS:
            return _manager

        if _manager is None:
            from app.services.core.llm_providers import LLMProviderManager
            from app.config import settings
            _manager = LLMProviderManager(default_ollama_host=settings.ollama_host)

        await _load_from_redis(_manager)
        _loaded_at = time.monotonic()

    return _manager


async def save_llm_config(manager, redis_url: str) -> None:
    """将 LLMProviderManager 当前状态持久化到 Redis，并刷新同进程缓存。"""
    global _manager, _loaded_at

    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        await r.set(REDIS_KEY, json.dumps(manager.to_config_dict()))
    except Exception as e:
        print(f"[LLMConfigStore] 保存配置失败: {e}")
    finally:
        await r.aclose()

    # 同进程立即生效：直接用刚保存的 manager 作为缓存
    _manager = manager
    _loaded_at = time.monotonic()


async def load_llm_config(manager, redis_url: str) -> bool:
    """从 Redis 恢复配置（向后兼容，新代码请用 get_llm_manager）。"""
    return await _load_from_redis(manager)


# ── 内部 ──

async def _load_from_redis(manager) -> bool:
    """从 Redis 读取配置并 restore 到 manager 实例。"""
    import redis.asyncio as aioredis
    from app.config import settings
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        data = await r.get(REDIS_KEY)
        if data:
            manager.restore_from_config_dict(json.loads(data))
            return True
        return False
    except Exception as e:
        print(f"[LLMConfigStore] 加载配置失败: {e}")
        return False
    finally:
        await r.aclose()
