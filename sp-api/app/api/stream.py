"""SSE endpoint — sp-api 版（仅 run-scoped，删 sessions）。

客户端订阅 `/api/stream/runs/{run_id}` 拿 fetcher / fulltext 进度事件；
backend worker 用 EventBus.publish_run_sync(run_id, ...) 推送。
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.event_bus import EventBus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stream", tags=["stream"])


async def _get_user_from_token(
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """SSE auth: EventSource 不能设 header，用 ?token=<jwt>。"""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


@router.get("/runs/{run_id}")
async def stream_run_events(
    run_id: str,
    request: Request,
    current_user: User = Depends(_get_user_from_token),
):
    """
    SSE: streams fetcher / fulltext events for a client-side run。

    Event types:
    - source_started / source_complete / source_error
    - doc_arrived
    - fulltext_progress / fulltext_done / fulltext_failed
    - run_complete / run_failed
    """
    async def event_generator():
        yield f"event: connected\ndata: {json.dumps({'run_id': run_id})}\n\n"

        try:
            async for event in EventBus.subscribe_run(run_id):
                if await request.is_disconnected():
                    break

                event_type = event.get("event", "message")
                data = json.dumps(event.get("data", {}), ensure_ascii=False, default=str)
                yield f"event: {event_type}\ndata: {data}\n\n"

                if event_type in ("run_complete", "run_failed"):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("[SSE] Stream error for run %s: %s", run_id, e)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
