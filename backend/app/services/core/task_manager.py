"""
Redis-backed 任务管理器
接口与 v1 的 in-memory 版本保持一致，内部改为 Redis 持久化
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import redis.asyncio as aioredis
from app.config import settings

TASK_TTL = 86400  # 24 小时


class TaskManager:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def _key(self, task_id: str) -> str:
        return f"urip:task:{task_id}"

    async def create_task(self, query: str, extra: Optional[Dict] = None) -> str:
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "query": query,
            "status": "pending",
            "progress": 0.0,
            "message": "等待中...",
            "result": None,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        }
        r = await self.get_redis()
        await r.setex(self._key(task_id), TASK_TTL, json.dumps(task))
        return task_id

    async def update_task(self, task_id: str, **kwargs) -> bool:
        r = await self.get_redis()
        raw = await r.get(self._key(task_id))
        if not raw:
            return False
        task = json.loads(raw)
        task.update(kwargs)
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        await r.setex(self._key(task_id), TASK_TTL, json.dumps(task))
        return True

    async def complete_task(self, task_id: str, result: Any) -> bool:
        return await self.update_task(task_id, status="completed", progress=1.0, result=result, message="完成")

    async def fail_task(self, task_id: str, error: str) -> bool:
        return await self.update_task(task_id, status="failed", error=error, message=f"失败: {error}")

    async def get_task(self, task_id: str) -> Optional[Dict]:
        r = await self.get_redis()
        raw = await r.get(self._key(task_id))
        if not raw:
            return None
        return json.loads(raw)

    async def close(self):
        if self._redis:
            await self._redis.close()


# 单例
task_manager = TaskManager()
