"""POST /api/conversation/sessions/{sid}/exit — 通用退出 endpoint。"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.conversation_session import ConversationSession
from app.models.user import User
from app.services import session_state_registry as ssr

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conversation/sessions", tags=["session-exit"])


CLEANUP_HINTS: dict[str, str] = {
    "intent_confirmation": "已丢弃项目草稿",
    "search_mode_selection": "已重置检索模式选择",
    "keyword_confirmation": "已取消当前轮次，关键词草稿清除",
    "classification": "当前轮次文献已保留，可从文献库重新分类",
    "round_finalize": "轮次已标记为未反馈关闭",
    "collaboration_selecting": "已清除协作范围草稿",
    "collaboration_active": "本次协作会话已结束",
    "monitoring_config": "监控配置草稿已清除",
}


def _append_flow_exited_message(
    session: ConversationSession,
    from_state: str,
    cleanup_summary: str,
) -> None:
    """将 flow_exited 富消息追加到 session.messages JSON 列表。"""
    messages = list(session.messages or [])
    messages.append(
        {
            "role": "system",
            "content": f"已退出 {from_state} 流程",
            "rich_type": "flow_exited",
            "rich_payload": {
                "from_state": from_state,
                "cleanup_summary": cleanup_summary,
                "at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
    session.messages = messages


@router.post("/{session_id}/exit")
async def exit_current_flow(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(ConversationSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")

    current_state = session.current_state or "idle"
    spec = ssr.get(current_state)
    if not spec.exitable:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NOT_EXITABLE",
                "current_state": current_state,
                "hint": "任务进行中或已是 idle；无需退出",
            },
        )

    redis: aioredis.Redis | None = None
    try:
        if spec.on_exit:
            redis = aioredis.from_url(settings.redis_url)
            await spec.on_exit(session, db, redis)
    except Exception as e:
        logger.exception("on_exit failed for state=%s: %s", current_state, e)
        raise HTTPException(status_code=500, detail=f"exit cleanup failed: {e}")
    finally:
        if redis is not None:
            await redis.aclose()

    session.current_state = "idle"
    cleanup_summary = CLEANUP_HINTS.get(current_state, "已退出")
    _append_flow_exited_message(session, current_state, cleanup_summary)
    await db.commit()

    return {
        "ok": True,
        "session_id": str(session.id),
        "rich_message": {
            "rich_type": "flow_exited",
            "from_state": current_state,
            "cleanup_summary": cleanup_summary,
        },
    }


# 用户在 FunctionDock 点"新检索"时专用：允许从 search_mode_selection / keyword_confirmation
# 强制回 idle（绕过 exitable=False 锁定）。其他运行态仍不允许。
RESET_FOR_NEW_ROUND_STATES = {"search_mode_selection", "keyword_confirmation"}


@router.post("/{session_id}/reset-for-new-round")
async def reset_for_new_round(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(ConversationSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")

    current_state = session.current_state or "idle"
    if current_state == "idle":
        return {"ok": True, "session_id": str(session.id), "noop": True}
    if current_state not in RESET_FOR_NEW_ROUND_STATES:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RESET_NOT_ALLOWED",
                "current_state": current_state,
                "hint": "当前状态不允许直接重开新检索，请先结束当前流程",
            },
        )

    spec = ssr.get(current_state)
    redis: aioredis.Redis | None = None
    try:
        if spec.on_exit:
            redis = aioredis.from_url(settings.redis_url)
            await spec.on_exit(session, db, redis)
    except Exception as e:
        logger.exception("reset on_exit failed for state=%s: %s", current_state, e)
        raise HTTPException(status_code=500, detail=f"reset cleanup failed: {e}")
    finally:
        if redis is not None:
            await redis.aclose()

    session.current_state = "idle"
    cleanup_summary = CLEANUP_HINTS.get(current_state, "已重置")
    _append_flow_exited_message(session, current_state, cleanup_summary)
    await db.commit()

    return {
        "ok": True,
        "session_id": str(session.id),
        "rich_message": {
            "rich_type": "flow_exited",
            "from_state": current_state,
            "cleanup_summary": cleanup_summary,
        },
    }
