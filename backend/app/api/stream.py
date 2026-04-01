"""
Server-Sent Events (SSE) endpoint for real-time search progress streaming.
Replaces 2-second HTTP polling with instant event delivery.
"""
import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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
    """SSE auth: EventSource can't set headers, so accept token via query param."""
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


@router.get("/rounds/{round_id}")
async def stream_round_events(
    round_id: str,
    request: Request,
    current_user: User = Depends(_get_user_from_token),
):
    """
    SSE endpoint: streams real-time events for a search round.

    Event types:
    - round_status: {status, progress, message}
    - source_started: {source_id, query}
    - source_complete: {source_id, count, time_ms}
    - source_error: {source_id, error}
    - doc_arrived: {external_id, source, title, doc_type}
    - summary_ready: {external_id, source, summary_preview, key_points}
    - agent_plan: {rationale, tools, year_range}
    - round_complete: {total, summaries_done}
    """
    async def event_generator():
        # Send initial heartbeat
        yield f"event: connected\ndata: {json.dumps({'round_id': round_id})}\n\n"

        try:
            async for event in EventBus.subscribe(round_id):
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                event_type = event.get("event", "message")
                data = json.dumps(event.get("data", {}), ensure_ascii=False, default=str)
                yield f"event: {event_type}\ndata: {data}\n\n"

                # Stop streaming on terminal events
                if event_type in ("round_complete", "round_failed"):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("[SSE] Stream error for round %s: %s", round_id, e)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
