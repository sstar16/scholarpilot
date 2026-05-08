"""Answer Now 辅助层: 把 partial 答案落 DB + 推 EventBus + 注入对话富消息.

被 Celery worker 在 stage 边界调用; 因此整个函数对异常做软处理 ——
即便 SSE 推送失败, DB 写入不能回滚.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_round import SearchRound
from app.services.event_bus import EventBus

logger = logging.getLogger(__name__)


async def deliver_partial_answer(
    round_id_str: str,
    partial_result: dict,
    db: AsyncSession,
) -> None:
    """把 Answer Now 部分答案落 DB + 推 EventBus + 同步对话气泡.

    Steps:
        1. UPDATE search_rounds SET status='partial_complete',
           partial_answer=<json>, partial_completed_at=now(),
           progress=1.0, progress_message='Answer Now 已合成部分结果'
        2. EventBus.publish_sync(round_id, 'round_status', ...)
        3. EventBus.publish_sync(round_id, 'partial_answer_ready', partial_result)
        4. inject_rich_message(rich_type='partial_answer', ...) ——
           尽力而为, 失败仅 log

    任何阶段抛异常都会被吞掉, 但会 log; worker 不能因 deliver 失败而崩.
    """
    if not round_id_str:
        logger.warning("[answer_now] deliver_partial_answer: empty round_id")
        return

    try:
        round_uuid = uuid.UUID(round_id_str)
    except (ValueError, TypeError) as e:
        logger.error("[answer_now] invalid round_id %r: %s", round_id_str, e)
        return

    # ---- 1. DB 落库 ----
    project_id_for_inject: uuid.UUID | None = None
    try:
        # 取 project_id 用于后面的 inject_rich_message
        from sqlalchemy import select as _select

        pid_q = await db.execute(
            _select(SearchRound.project_id).where(SearchRound.id == round_uuid)
        )
        project_id_for_inject = pid_q.scalar_one_or_none()

        await db.execute(
            update(SearchRound)
            .where(SearchRound.id == round_uuid)
            .values(
                status="partial_complete",
                partial_answer=partial_result,
                partial_completed_at=datetime.now(timezone.utc),
                progress=1.0,
                progress_message="Answer Now 已合成部分结果",
            )
        )
        await db.commit()
    except Exception as e:
        logger.exception(
            "[answer_now] DB update failed round=%s: %s",
            round_id_str[:8], e,
        )
        try:
            await db.rollback()
        except Exception:
            pass
        # DB 写不进去就别推 SSE 了 (前端拉 status 拿不到一致状态)
        return

    # ---- 2 & 3. EventBus 推送 ----
    try:
        EventBus.publish_sync(round_id_str, "round_status", {
            "status": "partial_complete",
            "progress": 1.0,
            "message": "Answer Now: 已合成部分结果",
            "partial_answer": partial_result,
        })
    except Exception as e:
        logger.warning("[answer_now] publish round_status failed: %s", e)

    try:
        EventBus.publish_sync(round_id_str, "partial_answer_ready", partial_result)
    except Exception as e:
        logger.warning("[answer_now] publish partial_answer_ready failed: %s", e)

    # ---- 4. 富消息注入 (best-effort) ----
    if project_id_for_inject is not None:
        try:
            from app.services.conversation_inject import inject_rich_message

            stage = partial_result.get("interrupted_at_stage", "?")
            doc_count = partial_result.get("doc_count_used", 0)
            await inject_rich_message(
                db,
                project_id=project_id_for_inject,
                rich_type="partial_answer",
                content=(
                    f"Answer Now: 在 {stage} 阶段中断, "
                    f"基于 {doc_count} 篇文献合成了部分答案"
                ),
                rich_data={
                    "round_id": round_id_str,
                    "partial_answer": partial_result,
                },
            )
        except Exception as e:
            # rich_type 'partial_answer' 可能未在 RICH_TYPES 注册 ——
            # 这里失败不影响主流程 (前端 SSE 已收到 partial_answer_ready)
            logger.warning(
                "[answer_now] inject_rich_message failed (non-fatal): %s", e,
            )
