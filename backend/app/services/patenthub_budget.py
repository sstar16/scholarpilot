"""
PatentHub PDF 下载单轮预算守门（方案 B）。

单价：PDF = 1 元/次 + 前置详情 0.1 元/次 = **每篇 ¥1.1**（2026-04-24 patenthub 工作人员确认详情与搜索共享计费）。
项目策略（2026-04-24 锁定）：
- 每个 round 最多消耗 N **篇 PDF**（默认 5，由 settings.max_patenthub_pdf_per_round 控制）
- 5 篇 PDF 实际消耗 ≈ 1 次搜索(0.1) + 5 次详情(0.5) + 5 次 PDF(5) = ¥5.6 / 轮
- 所有下载路径（用户点击 / 自动 very_relevant / AI deep dive）**统一过守门**（按篇数计，不按分钱计）
- 超额：try_consume 返回 False，调用方拒绝下载，前端 toast 提示

Redis key: `patenthub:pdf_budget:{round_id}`（int 计数）
TTL: 30 天（一轮生命周期够用）
"""
import logging
import uuid
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

REDIS_KEY_TEMPLATE = "patenthub:pdf_budget:{round_id}"
REDIS_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 天


def _redis_key(round_id: str) -> str:
    return REDIS_KEY_TEMPLATE.format(round_id=round_id)


async def _redis():
    import redis.asyncio as aioredis
    from app.config import settings
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def get_max() -> int:
    """读单轮预算上限。0 或负数视为"禁用"（全部拒绝）。"""
    from app.config import settings
    return int(getattr(settings, "max_patenthub_pdf_per_round", 5) or 0)


async def get_used(round_id: str) -> int:
    """读当前 round 已消费次数。无记录 = 0。"""
    r = await _redis()
    try:
        raw = await r.get(_redis_key(round_id))
        return int(raw) if raw else 0
    finally:
        await r.aclose()


async def get_budget_status(round_id: str) -> dict:
    """前端展示用。返回 {used, max, remaining, exhausted}。"""
    mx = get_max()
    used = await get_used(round_id)
    remaining = max(0, mx - used)
    return {
        "round_id": round_id,
        "used": used,
        "max": mx,
        "remaining": remaining,
        "exhausted": remaining <= 0,
    }


async def try_consume(round_id: str, force: bool = False) -> Tuple[bool, int, int]:
    """
    乐观预扣：INCR 一次。
    - force=False（默认，自动路径 / 用户首次点击）：超额立刻 DECR 回退并拒绝 → 前端弹二次确认
    - force=True（用户在二次弹窗里选"继续"）：直接扣费，不检查上限
    成功下载后无需额外调用（已扣）；失败需调 refund 回退。

    返回 (ok, used_after, max)。ok=False 时 used_after 是"已用完的上限值"。
    """
    mx = get_max()
    if mx <= 0 and not force:
        logger.warning("[PatentHubBudget] max=%d，非强制模式拒绝下载（MAX_PATENTHUB_PDF_PER_ROUND=0）", mx)
        return (False, 0, mx)

    r = await _redis()
    try:
        key = _redis_key(round_id)
        new_count = await r.incr(key)
        if new_count == 1:
            await r.expire(key, REDIS_TTL_SECONDS)

        if not force and new_count > mx:
            await r.decr(key)
            logger.info("[PatentHubBudget] round=%s 软超额 %d/%d，返前端二次确认",
                        round_id[:8], mx, mx)
            return (False, mx, mx)

        if force and new_count > mx:
            logger.info("[PatentHubBudget] round=%s 强制扣费 %d/%d（用户二次确认后越权）",
                        round_id[:8], new_count, mx)
        else:
            logger.info("[PatentHubBudget] round=%s 预扣成功 %d/%d", round_id[:8], new_count, mx)
        return (True, new_count, mx)
    finally:
        await r.aclose()


async def refund(round_id: str) -> None:
    """下载失败时回退计数（允许用户重试不扣费）。不会减到负数。"""
    r = await _redis()
    try:
        key = _redis_key(round_id)
        raw = await r.get(key)
        current = int(raw) if raw else 0
        if current > 0:
            await r.decr(key)
            logger.info("[PatentHubBudget] round=%s 已回退 %d→%d", round_id[:8], current, current - 1)
    finally:
        await r.aclose()


async def resolve_round_id(
    db,
    document_id: uuid.UUID,
    project_id: uuid.UUID,
) -> Optional[str]:
    """
    反查某个 doc 属于哪一轮（守门 key 用）。
    优先：DocumentClassification.classified_in_round_id（用户已分类的）
    兜底：RoundDocument.round_id（doc 出现过的最晚一轮）
    """
    from sqlalchemy import select
    from app.models.document_classification import DocumentClassification
    from app.models.round_document import RoundDocument
    from app.models.search_round import SearchRound

    row = (await db.execute(
        select(DocumentClassification.classified_in_round_id)
        .where(
            DocumentClassification.document_id == document_id,
            DocumentClassification.project_id == project_id,
        )
        .limit(1)
    )).first()
    if row and row[0]:
        return str(row[0])

    row = (await db.execute(
        select(RoundDocument.round_id)
        .join(SearchRound, SearchRound.id == RoundDocument.round_id)
        .where(
            RoundDocument.document_id == document_id,
            SearchRound.project_id == project_id,
        )
        .order_by(SearchRound.round_number.desc())
        .limit(1)
    )).first()
    if row and row[0]:
        return str(row[0])

    return None
