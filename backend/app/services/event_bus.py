"""
Redis Pub/Sub event bus for real-time SSE streaming.
Worker processes publish events, FastAPI SSE endpoint subscribes.
Supports round-scoped (sse:round:*) and session-scoped (sse:session:*) channels.
"""
import json
import logging
from typing import AsyncGenerator
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)

ROUND_CHANNEL_PREFIX = "sse:round:"
SESSION_CHANNEL_PREFIX = "sse:session:"

# Keep backward-compat alias
CHANNEL_PREFIX = ROUND_CHANNEL_PREFIX


class EventBus:
    """Redis-backed event bus for SSE streaming"""

    # ==================== Round-scoped (existing) ====================

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

    # ==================== Session-scoped (new for workbench) ====================

    @staticmethod
    async def publish_session(session_id: str, event_type: str, data: dict):
        """Publish a workbench event to the session channel."""
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            channel = f"{SESSION_CHANNEL_PREFIX}{session_id}"
            payload = json.dumps({"event": event_type, "data": data}, ensure_ascii=False, default=str)
            await r.publish(channel, payload)
        finally:
            await r.aclose()

    @staticmethod
    async def subscribe_session(session_id: str) -> AsyncGenerator[dict, None]:
        """Subscribe to workbench events for a conversation session."""
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            pubsub = r.pubsub()
            channel = f"{SESSION_CHANNEL_PREFIX}{session_id}"
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
    def publish_session_sync(session_id: str, event_type: str, data: dict):
        """Synchronous publish for use inside Celery tasks."""
        import redis
        r = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            channel = f"{SESSION_CHANNEL_PREFIX}{session_id}"
            payload = json.dumps({"event": event_type, "data": data}, ensure_ascii=False, default=str)
            r.publish(channel, payload)
        finally:
            r.close()
