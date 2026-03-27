"""
LLM 提供商配置的 Redis 持久化
保存/加载 key: llm:config
"""
import json

REDIS_KEY = "llm:config"


async def save_llm_config(manager, redis_url: str) -> None:
    """将 LLMProviderManager 当前状态持久化到 Redis"""
    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        await r.set(REDIS_KEY, json.dumps(manager.to_config_dict()))
    except Exception as e:
        print(f"[LLMConfigStore] 保存配置失败: {e}")
    finally:
        await r.aclose()


async def load_llm_config(manager, redis_url: str) -> bool:
    """从 Redis 恢复 LLMProviderManager 配置，返回是否成功加载"""
    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url, decode_responses=True)
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
