"""
Batch-buffered log writer for DevTools.
Collects log entries in memory and flushes to PostgreSQL in batches.
Also publishes to Redis Pub/Sub for real-time WebSocket push.
"""
import asyncio
import json
import logging
import threading
from collections import deque, OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.config import settings

logger = logging.getLogger("devtools.log_writer")

FLUSH_THRESHOLD = 50
FLUSH_INTERVAL_S = 2.0
BUFFER_MAX = 200
REDIS_CHANNEL = "devtools:logs"

_INSERT_SQL = text("""
    INSERT INTO dev_logs (created_at, level, source, category, message, context, round_id, project_id, duration_ms, error_trace)
    VALUES (:created_at, :level, :source, :category, :message, :context, :round_id, :project_id, :duration_ms, :error_trace)
""")


class _BoundedDict(OrderedDict):
    """OrderedDict with a max size — evicts oldest on overflow."""
    def __init__(self, maxsize=1000):
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self._maxsize:
            self.popitem(last=False)


class LogBuffer:
    """Thread-safe log buffer with async and sync flush support."""

    def __init__(self):
        self._buffer: deque[dict] = deque(maxlen=BUFFER_MAX)
        self._lock = threading.Lock()
        self._async_task: asyncio.Task | None = None
        self._redis_sync = None
        # Cached engines (C1 fix: reuse instead of creating per-flush)
        self._async_engine = None
        self._sync_engine = None

    def add(self, entry: dict[str, Any]) -> None:
        """Add a log entry to the buffer. Thread-safe."""
        if "created_at" not in entry:
            entry["created_at"] = datetime.now(timezone.utc)
        # Ensure all INSERT fields have a value (None for nullable columns)
        for key in ("category", "context", "round_id", "project_id", "duration_ms", "error_trace"):
            entry.setdefault(key, None)
        # Ensure context is JSON-serializable string for PG
        if entry["context"] is not None:
            if not isinstance(entry["context"], str):
                entry["context"] = json.dumps(entry["context"], default=str, ensure_ascii=False)

        with self._lock:
            self._buffer.append(entry)

        # Publish to Redis for real-time WebSocket (best-effort, sync for Celery)
        self._publish_to_redis_sync(entry)

        if len(self._buffer) >= FLUSH_THRESHOLD:
            self._trigger_flush()

    def _publish_to_redis_sync(self, entry: dict) -> None:
        """Best-effort publish to Redis Pub/Sub (sync, thread-safe)."""
        try:
            if self._redis_sync is None:
                import redis
                self._redis_sync = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            pub_data = {
                "created_at": entry["created_at"].isoformat() if isinstance(entry["created_at"], datetime) else str(entry["created_at"]),
                "level": entry.get("level", "INFO"),
                "source": entry.get("source", "unknown"),
                "category": entry.get("category"),
                "message": entry.get("message", ""),
                "round_id": str(entry["round_id"]) if entry.get("round_id") else None,
                "project_id": str(entry["project_id"]) if entry.get("project_id") else None,
                "duration_ms": entry.get("duration_ms"),
                "error_trace": entry.get("error_trace"),
                "context": json.loads(entry["context"]) if isinstance(entry.get("context"), str) else entry.get("context"),
            }
            self._redis_sync.publish(REDIS_CHANNEL, json.dumps(pub_data, ensure_ascii=False))
        except Exception:
            pass  # best-effort, don't break log collection

    def _trigger_flush(self) -> None:
        """Trigger flush based on current context (async or sync)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.async_flush())
        except RuntimeError:
            self.sync_flush()

    def _get_async_engine(self):
        """Lazily create and cache async engine."""
        if self._async_engine is None:
            self._async_engine = create_async_engine(
                settings.database_url, echo=False, pool_size=2, max_overflow=3
            )
        return self._async_engine

    def _get_sync_engine(self):
        """Lazily create and cache sync engine."""
        if self._sync_engine is None:
            from sqlalchemy import create_engine
            sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
            self._sync_engine = create_engine(
                sync_url, echo=False, pool_size=2, max_overflow=3
            )
        return self._sync_engine

    async def async_flush(self) -> None:
        """Flush buffer to PG using async engine (for FastAPI process)."""
        entries = self._drain()
        if not entries:
            return
        try:
            engine = self._get_async_engine()
            async with AsyncSession(engine) as session:
                for entry in entries:
                    await session.execute(_INSERT_SQL, entry)
                await session.commit()
        except Exception as e:
            logger.warning("DevTools log flush failed: %s", e)

    def sync_flush(self) -> None:
        """Flush buffer to PG using sync connection (for Celery worker)."""
        entries = self._drain()
        if not entries:
            return
        try:
            from sqlalchemy.orm import Session
            engine = self._get_sync_engine()
            with Session(engine) as session:
                for entry in entries:
                    session.execute(_INSERT_SQL, entry)
                session.commit()
        except Exception as e:
            logger.warning("DevTools log sync flush failed: %s", e)

    def _drain(self) -> list[dict]:
        """Drain all entries from buffer. Thread-safe."""
        with self._lock:
            entries = list(self._buffer)
            self._buffer.clear()
        return entries

    async def start_periodic_flush(self) -> None:
        """Start periodic flush task (call once in FastAPI lifespan)."""
        async def _flusher():
            while True:
                await asyncio.sleep(FLUSH_INTERVAL_S)
                await self.async_flush()
        self._async_task = asyncio.create_task(_flusher())

    async def stop(self) -> None:
        """Stop periodic flush and drain remaining."""
        if self._async_task:
            self._async_task.cancel()
            try:
                await self._async_task
            except asyncio.CancelledError:
                pass
        await self.async_flush()
        if self._async_engine:
            await self._async_engine.dispose()
        if self._sync_engine:
            self._sync_engine.dispose()


# Global singleton
log_buffer = LogBuffer()
