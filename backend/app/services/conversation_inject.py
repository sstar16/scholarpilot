"""
Rich-message injection helper.

Used by API and Celery workers to append rich messages (keyword confirmation,
search progress, round results, collaboration events, ...) into the user's
active ConversationSession.messages JSONB column so the chat-centric UI
can render them as inline rich bubbles and a page refresh restores the flow.

API layer (async):
    from app.services.conversation_inject import inject_rich_message
    await inject_rich_message(
        db,
        project_id=project.id,
        rich_type="keyword_confirmation",
        content="我为您生成了本轮检索关键词，请确认",
        rich_data={"round_id": str(round_.id), "source_plans": {...}},
    )

Celery worker (needs its own event loop via _run_async):
    from app.services.conversation_inject import inject_rich_message_sync
    inject_rich_message_sync(
        project_id=project_id,
        rich_type="search_progress",
        rich_data={...},
        content="检索进行中...",
    )
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.conversation_session import ConversationSession

logger = logging.getLogger(__name__)

RICH_TYPES = frozenset({
    "keyword_confirmation",
    "search_progress",
    "round_results",
    "round_complete",
    "document_snippet",
    "collaboration_scope",       # 让用户选协作文献
    "collaboration_started",     # 协作模式开始 banner
    "collaboration_read_plan",   # vibe 模式：LLM 的调研计划（等用户确认 picks + kg_queries）
    "collaboration_answer",      # research_agent 回答
    "collaboration_ended",       # 协作模式退出
    "card_update_suggestion",    # 协作回答后的 doc card 字段更新建议
    "pdf_import_parsing",        # M2: PDF 上传成功，解析中
    "pdf_import_editing",        # M2: PDF 解析完成，等待用户确认元数据
    "pdf_import_scoring",        # M2: 元数据已确认，AI 评分中
    "pdf_import_failed",         # M2: PDF 解析失败通知
    "pdf_import_final_card",     # M2: 评分完成，文献就绪
    "pdf_import_cancelled",      # M2: 用户取消上传
    "skill_suggestion",          # B3/C1: Skill Recommender Hook 推送的智能技能推荐
    "partial_answer",            # Answer Now 快通道：长检索流程被用户中断后的 best-effort 答案
    "feature_gate_blocked",      # 功能拦截提示（额度不足 / 权限不够等）
    "feature_gate_allowed",      # 功能可用（目前仅 HTTP 响应，未注入 session.messages）
    "flow_exited",               # session_exit.py 的退出通知（system 角色）
    "stale_hint",                # 距上次检索 N 天的软提示（idle 状态不打断，鼓励触发新轮）
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load_session(
    db: AsyncSession,
    session_id: Optional[uuid.UUID],
    project_id: Optional[uuid.UUID],
) -> Optional[ConversationSession]:
    if session_id:
        res = await db.execute(
            select(ConversationSession).where(ConversationSession.id == session_id)
        )
        return res.scalar_one_or_none()
    if project_id:
        res = await db.execute(
            select(ConversationSession)
            .where(
                ConversationSession.project_id == project_id,
                ConversationSession.is_active == True,  # noqa: E712
            )
            .order_by(ConversationSession.updated_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()
    return None


async def inject_rich_message(
    db: AsyncSession,
    *,
    rich_type: str,
    content: str,
    rich_data: Optional[dict] = None,
    session_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
    role: str = "assistant",
    metadata: Optional[dict] = None,
    commit: bool = True,
) -> bool:
    """
    Async variant. Returns True on success, False if no session was found.
    """
    if rich_type not in RICH_TYPES:
        logger.warning("[inject_rich_message] unknown rich_type=%s", rich_type)

    session = await _load_session(db, session_id, project_id)
    if not session:
        logger.info(
            "[inject_rich_message] no active session (sid=%s pid=%s) — skip %s",
            session_id, project_id, rich_type,
        )
        return False

    msgs = list(session.messages or [])

    # 去重：对于"按 round_id 唯一"的富消息类型，如果同 round_id 已存在则
    # 替换现有的（让 rich_data 拿到最新数据），而不是追加。这避免了：
    # - 用户多次点击"开始检索"导致 prepare_round 被调用多次
    # - 后端阶段切换时重复 inject keyword_confirmation/round_complete
    UNIQUE_BY_ROUND = {"keyword_confirmation", "round_complete"}
    new_round_id = (rich_data or {}).get("round_id")
    if rich_type in UNIQUE_BY_ROUND and new_round_id:
        replaced = False
        for i, m in enumerate(msgs):
            if (
                m.get("rich_type") == rich_type
                and (m.get("rich_data") or {}).get("round_id") == new_round_id
            ):
                msgs[i] = {
                    "role": role,
                    "content": content,
                    "timestamp": _now_iso(),
                    "metadata": {"source": "rich_injection", **(metadata or {})},
                    "rich_type": rich_type,
                    "rich_data": rich_data or {},
                }
                replaced = True
                logger.info(
                    "[inject_rich_message] dedup: replaced existing %s for round=%s",
                    rich_type, new_round_id,
                )
                break
        if not replaced:
            msgs.append({
                "role": role,
                "content": content,
                "timestamp": _now_iso(),
                "metadata": {"source": "rich_injection", **(metadata or {})},
                "rich_type": rich_type,
                "rich_data": rich_data or {},
            })
    else:
        msgs.append({
            "role": role,
            "content": content,
            "timestamp": _now_iso(),
            "metadata": {"source": "rich_injection", **(metadata or {})},
            "rich_type": rich_type,
            "rich_data": rich_data or {},
        })

    session.messages = msgs
    flag_modified(session, "messages")

    if commit:
        await db.commit()

    logger.info(
        "[inject_rich_message] %s → session=%s (total=%d)",
        rich_type, session.id, len(msgs),
    )

    # SSE 广播：让订阅该 session 的前端立即收到新消息，不用等轮询/刷新
    try:
        from app.services.event_bus import EventBus
        await EventBus.publish_session(
            str(session.id),
            "session_message_appended",
            msgs[-1],  # 最后一条消息（刚 append 或 replace 的那条）
        )
    except Exception as e:
        logger.warning("[inject_rich_message] SSE broadcast failed: %s", e)

    return True


def inject_rich_message_sync(
    *,
    rich_type: str,
    content: str,
    rich_data: Optional[dict] = None,
    session_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
    role: str = "assistant",
    metadata: Optional[dict] = None,
) -> bool:
    """
    Celery-worker-friendly wrapper. Spins up a fresh async engine session,
    injects, commits, disposes. Safe to call from sync task body.
    """
    from app.workers.search_tasks import _run_async
    from app.database import AsyncSessionLocal

    async def _do() -> bool:
        async with AsyncSessionLocal() as db:
            return await inject_rich_message(
                db,
                rich_type=rich_type,
                content=content,
                rich_data=rich_data,
                session_id=session_id,
                project_id=project_id,
                role=role,
                metadata=metadata,
                commit=True,
            )

    try:
        return _run_async(_do())
    except Exception as exc:
        logger.warning("[inject_rich_message_sync] %s failed: %s", rich_type, exc)
        return False


async def resolve_session_id_for_project(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> Optional[uuid.UUID]:
    """Utility: find the latest active session bound to a project."""
    session = await _load_session(db, None, project_id)
    return session.id if session else None


async def enter_keyword_confirmation_state(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    commit: bool = True,
) -> bool:
    """把活跃 session 推进到 keyword_confirmation 状态并登记 current_round_id。

    这是 prepare_round / FunctionDock "新检索" 路径的 session-state 同步入口。
    未来 _exit_keyword 依赖 state_data["current_round_id"] 来定位要 cancel 的 round。
    """
    session = await _load_session(db, None, project_id)
    if not session:
        logger.info(
            "[enter_keyword_confirmation_state] no active session for pid=%s", project_id
        )
        return False
    session.current_state = "keyword_confirmation"
    state_data = dict(session.state_data or {})
    state_data["current_round_id"] = str(round_id)
    session.state_data = state_data
    flag_modified(session, "state_data")
    if commit:
        await db.commit()
    return True
