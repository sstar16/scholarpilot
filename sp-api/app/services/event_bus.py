"""
Redis Pub/Sub event bus — sp-api 版本（仅 run-scoped）。

vs backend/app/services/event_bus.py 改动：
- 删 publish_session/subscribe_session/publish_session_sync（sp-api 不维护 ConversationSession）
- 仅保留 run-scoped 通道（client_run_id 直接当 round_id 用）

Worker processes publish events, FastAPI SSE endpoint subscribes.
"""
import json
import logging
from typing import AsyncGenerator
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)

ROUND_CHANNEL_PREFIX = "sse:round:"

# Keep backward-compat alias
CHANNEL_PREFIX = ROUND_CHANNEL_PREFIX


class EventBus:
    """Redis-backed event bus for SSE streaming"""

    @staticmethod
    async def publish(round_id: str, event_type: str, data: dict):
        """Publish an event to Redis channel (called from async context)"""
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            channel = f"{ROUND_CHANNEL_PREFIX}{round_id}"
            payload = json.dumps({"event": event_type, "data": data}, ensure_ascii=False, default=str)
            await r.publish(channel, payload)
        finally:
            await r.aclose()

    # 显式别名（fetcher.py / fulltext.py 用 publish_run 更语义化）
    @staticmethod
    async def publish_run(run_id: str, event_type: str, data: dict):
        await EventBus.publish(run_id, event_type, data)

    @staticmethod
    async def subscribe(round_id: str) -> AsyncGenerator[dict, None]:
        """Subscribe to events for a round (used by SSE endpoint)"""
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            pubsub = r.pubsub()
            channel = f"{ROUND_CHANNEL_PREFIX}{round_id}"
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        yield json.loads(message["data"])
                    except json.JSONDecodeError:
                        continue
        finally:
            await pubsub.unsubscribe()
            await r.aclose()

    @staticmethod
    async def subscribe_run(run_id: str) -> AsyncGenerator[dict, None]:
        async for ev in EventBus.subscribe(run_id):
            yield ev

    @staticmethod
    def publish_sync(round_id: str, event_type: str, data: dict):
        """Synchronous publish for use inside Celery tasks"""
        import redis
        r = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            channel = f"{ROUND_CHANNEL_PREFIX}{round_id}"
            payload = json.dumps({"event": event_type, "data": data}, ensure_ascii=False, default=str)
            r.publish(channel, payload)
        finally:
            r.close()

    @staticmethod
    def publish_run_sync(run_id: str, event_type: str, data: dict):
        EventBus.publish_sync(run_id, event_type, data)
