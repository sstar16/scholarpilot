"""
POST_FEEDBACK hook — 智能 Skill 推荐（B3）

触发时机：用户提交一轮 feedback 后（feedback.py:189 fire POST_FEEDBACK）
动作：
  1. 查询本轮 bucket 分布
  2. 按规则匹配推荐 skill
  3. 通过 inject_rich_message 推送 rich_type="skill_suggestion" 到 session
用户点一下即可执行对应 skill，把 Hook 系统从"仅 log"升级为"驱动 UX"。

推荐规则（按优先级，只推最高级的 1 个）：
  - irrelevant >= 40% → gap_finder（可能检索盲区）
  - very_relevant / highly_relevant >= 3 → trend_spotter（看趋势）
  - highly_relevant >= 1 → deep_dive（深挖首个高分文献）
  - 其他 → 不推荐（避免骚扰）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.harness.hook_engine import HookEngine, HookPoint

logger = logging.getLogger(__name__)


async def recommend_skill_after_feedback(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """核心 handler —— 失败静默，不影响主 feedback 流程。"""
    project_id = ctx.get("project_id")
    round_id = ctx.get("round_id")
    if not project_id or not round_id:
        return ctx

    try:
        recommendation = await _analyze_feedback(project_id, round_id)
    except Exception as e:
        logger.debug("[skill_recommender] analyze failed (benign): %s", e)
        return ctx

    if not recommendation:
        return ctx

    try:
        await _inject_recommendation(project_id, round_id, recommendation)
    except Exception as e:
        logger.debug("[skill_recommender] inject failed (benign): %s", e)

    return ctx


async def _analyze_feedback(
    project_id: str, round_id: str,
) -> Optional[Dict[str, Any]]:
    """返回 {skill_id, reason, bucket_stats} 或 None。"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, func
    from app.config import settings
    from app.models.feedback import Feedback

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            res = await db.execute(
                select(Feedback.relevance, func.count())
                .where(Feedback.round_id == round_id)
                .group_by(Feedback.relevance)
            )
            counts: Dict[int, int] = {row[0]: row[1] for row in res.all()}

        total = sum(counts.values())
        if total == 0:
            return None

        highly = counts.get(2, 0)
        relevant = counts.get(1, 0)
        irrelevant = counts.get(-1, 0)
        stats = {
            "total": total,
            "highly_relevant": highly,
            "relevant": relevant,
            "neutral": counts.get(0, 0),
            "irrelevant": irrelevant,
        }

        irrelevant_ratio = irrelevant / total

        if irrelevant_ratio >= 0.4:
            return {
                "skill_id": "gap_finder",
                "display_name": "Gap Finder",
                "reason": f"本轮 {irrelevant}/{total} 篇被标为不相关，可能存在检索盲区",
                "bucket_stats": stats,
            }

        if (highly + relevant) >= 3:
            return {
                "skill_id": "trend_spotter",
                "display_name": "Trend Spotter",
                "reason": f"本轮收获 {highly + relevant} 篇高价值文献，适合看趋势",
                "bucket_stats": stats,
            }

        if highly >= 1:
            return {
                "skill_id": "deep_dive",
                "display_name": "Deep Dive",
                "reason": "有 1+ 篇强相关文献，可深挖其方法/结果/引用",
                "bucket_stats": stats,
            }

        return None
    finally:
        await engine.dispose()


async def _inject_recommendation(
    project_id: str, round_id: str, recommendation: Dict[str, Any],
) -> None:
    """推送 rich_type="skill_suggestion" 气泡到对应 session。"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.conversation_session import ConversationSession
    from app.services.conversation_inject import inject_rich_message

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            res = await db.execute(
                select(ConversationSession.id).where(
                    ConversationSession.project_id == project_id,
                ).order_by(ConversationSession.updated_at.desc()).limit(1)
            )
            session_id = res.scalar_one_or_none()
            if not session_id:
                return

            await inject_rich_message(
                db,
                session_id=session_id,
                rich_type="skill_suggestion",
                content=f"💡 建议尝试 {recommendation['display_name']}：{recommendation['reason']}",
                rich_data={
                    "skill_id": recommendation["skill_id"],
                    "display_name": recommendation["display_name"],
                    "reason": recommendation["reason"],
                    "project_id": str(project_id),
                    "round_id": str(round_id),
                    "bucket_stats": recommendation["bucket_stats"],
                },
            )
            await db.commit()
            logger.info(
                "[skill_recommender] pushed suggestion=%s for round=%s",
                recommendation["skill_id"], str(round_id)[:8],
            )
    finally:
        await engine.dispose()


def register_skill_recommender_hook(engine: HookEngine) -> None:
    """main.py lifespan 中调用，注册 POST_FEEDBACK handler。"""
    engine.register(
        HookPoint.POST_FEEDBACK,
        recommend_skill_after_feedback,
        name="skill_recommender",
        priority=50,
    )
