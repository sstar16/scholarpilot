"""SessionStateRegistry — 每个 state 的元信息 + 退出副作用。"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.models.conversation_session import ConversationSession
from app.models.search_round import SearchRound

logger = logging.getLogger(__name__)


OnExitCallable = Callable[[ConversationSession, AsyncSession, Redis], Awaitable[None]]


@dataclass
class StateSpec:
    name: str
    exitable: bool
    on_exit: Optional[OnExitCallable] = None


# ---------- on_exit 回调 ----------

async def _exit_intent(session, db, redis):
    if session.state_data:
        session.state_data = dict(session.state_data)
        session.state_data.pop("project_draft", None)


async def _exit_mode_selection(session, db, redis):
    if not session.state_data:
        return
    state = dict(session.state_data)
    round_id_str = state.get("current_round_id")
    if round_id_str:
        round_obj = await db.get(SearchRound, uuid.UUID(round_id_str))
        if round_obj and round_obj.status in ("pending", "search_mode_selection"):
            round_obj.search_mode = None
    session.state_data = state


async def _exit_keyword(session, db, redis):
    state = dict(session.state_data or {})
    round_id_str = state.get("current_round_id")
    round_obj = None

    if round_id_str:
        round_obj = await db.get(SearchRound, uuid.UUID(round_id_str))

    # Fallback: 旧 session 未登记 current_round_id 时，通过 project.current_round
    # 定位当前轮次（避免"reset 空操作"导致 round 悬挂在 awaiting_keywords）
    if round_obj is None and session.project_id:
        from sqlalchemy import select
        from app.models.project import Project as _Proj
        project = await db.get(_Proj, session.project_id)
        if project and project.current_round > 0:
            r = await db.execute(
                select(SearchRound).where(
                    SearchRound.project_id == project.id,
                    SearchRound.round_number == project.current_round,
                )
            )
            round_obj = r.scalar_one_or_none()

    if round_obj is not None:
        await redis.delete(f"keyword_plan:{round_obj.id}")
        if round_obj.status not in (
            "awaiting_feedback", "complete", "closed", "cancelled", "closed_no_feedback"
        ):
            round_obj.status = "cancelled"
            round_obj.cancelled_reason = "user_exit_keyword_confirmation"
            round_obj.cancelled_at = datetime.now(timezone.utc)

    state.pop("current_round_id", None)
    session.state_data = state


async def _exit_classification(session, db, redis):
    # 分类态退出不破坏数据（文献保留可再分类），仅清 session 指针
    pass


async def _exit_round_finalize(session, db, redis):
    if not session.state_data:
        return
    state = dict(session.state_data)
    round_id_str = state.get("current_round_id")
    if round_id_str:
        round_obj = await db.get(SearchRound, uuid.UUID(round_id_str))
        if round_obj and round_obj.status == "awaiting_feedback":
            round_obj.status = "closed_no_feedback"
    session.state_data = state


async def _exit_collab_selecting(session, db, redis):
    if not session.state_data:
        return
    state = dict(session.state_data)
    state.pop("collab_scope_draft", None)
    session.state_data = state


async def _exit_collab_active(session, db, redis):
    # 归档逻辑保留给现有 /collaboration/exit endpoint；此处仅清草稿指针
    if not session.state_data:
        return
    state = dict(session.state_data)
    state.pop("collab_scope", None)
    session.state_data = state


# ---------- REGISTRY ----------

REGISTRY: dict[str, StateSpec] = {
    "idle":                    StateSpec("idle", exitable=False),
    "intent_analysis":         StateSpec("intent_analysis", exitable=False),
    "intent_confirmation":     StateSpec("intent_confirmation", exitable=True, on_exit=_exit_intent),
    # 检索流程一旦开启完全不可逆：从 search_mode_selection 到 round_finalize 全部锁死，
    # 唯一出路是用户主动点「结束本轮」（finalize_round 端点），结束后自然回 idle。
    "search_mode_selection":   StateSpec("search_mode_selection", exitable=False, on_exit=_exit_mode_selection),
    "keyword_confirmation":    StateSpec("keyword_confirmation", exitable=False, on_exit=_exit_keyword),
    "searching":               StateSpec("searching", exitable=False),
    "scoring":                 StateSpec("scoring", exitable=False),
    "classification":          StateSpec("classification", exitable=False, on_exit=_exit_classification),
    "round_finalize":          StateSpec("round_finalize", exitable=False, on_exit=_exit_round_finalize),
    "exit_decision":           StateSpec("exit_decision", exitable=False),
    "monitoring_config":       StateSpec("monitoring_config", exitable=True, on_exit=_exit_intent),
    "investigation":           StateSpec("investigation", exitable=False),
    # 选文献阶段不暴露 × 退出；放弃选择走气泡内部"取消"按钮即可
    "collaboration_selecting": StateSpec("collaboration_selecting", exitable=False, on_exit=_exit_collab_selecting),
    "collaboration_active":    StateSpec("collaboration_active", exitable=True, on_exit=_exit_collab_active),
}


def exitable_states() -> set[str]:
    return {name for name, spec in REGISTRY.items() if spec.exitable}


def get(state: str) -> StateSpec:
    """返回 state spec；未注册的状态默认 unexitable 且无副作用。"""
    if state not in REGISTRY:
        logger.warning("unknown session state %s, treating as non-exitable", state)
        return StateSpec(state, exitable=False)
    return REGISTRY[state]
