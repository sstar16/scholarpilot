"""
PatentHub PDF 下载预算守门 — sp-api 客户端版本。

vs backend/app/services/patenthub_budget.py 改动：
- 删 resolve_round_id（依赖已删除的 backend RoundDocument/SearchRound 表）
- 换 derive_budget_key(client_run_id, user_id) 作为预算 key 来源
- 客户端把 client_run_id（可以是项目轮次 / 客户端发起的检索 ID）传给 sp-api，
  sp-api 不查 DB，只按 user+run 维度聚合。

单价：PDF = 1 元/次 + 前置详情 0.1 元/次 = **每篇 ¥1.1**（2026-04-24 patenthub 工作人员确认）。

Redis key: `patenthub:pdf_budget:{key}`（int 计数）
TTL: 30 天（一轮生命周期够用）
"""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

REDIS_KEY_TEMPLATE = "patenthub:pdf_budget:{key}"
REDIS_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 天


def derive_budget_key(client_run_id: str, user_id: str) -> str:
    """
    生成预算守门 Redis key 的 key 部分。
    客户端 backend 不再依赖 SearchRound 等 DB 表，按 user+client_run_id 双维度聚合。
    """
    return f"user:{user_id}:run:{client_run_id}"


def _redis_key(key: str) -> str:
    return REDIS_KEY_TEMPLATE.format(key=key)


async def _redis():
    import redis.asyncio as aioredis
    from app.config import settings
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def get_max() -> int:
    """读单轮预算上限。0 或负数视为"禁用"（全部拒绝）。"""
    from app.config import settings
    return int(getattr(settings, "max_patenthub_pdf_per_round", 5) or 0)


async def get_used(key: str) -> int:
    """读当前 key 已消费次数。无记录 = 0。"""
    r = await _redis()
    try:
        raw = await r.get(_redis_key(key))
        return int(raw) if raw else 0
    finally:
        await r.aclose()


async def get_budget_status(key: str) -> dict:
    """前端展示用。返回 {used, max, remaining, exhausted}。"""
    mx = get_max()
    used = await get_used(key)
    remaining = max(0, mx - used)
    return {
        "key": key,
        "used": used,
        "max": mx,
        "remaining": remaining,
        "exhausted": remaining <= 0,
    }


async def try_consume(key: str, force: bool = False) -> Tuple[bool, int, int]:
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
        rkey = _redis_key(key)
        new_count = await r.incr(rkey)
        if new_count == 1:
            await r.expire(rkey, REDIS_TTL_SECONDS)

        if not force and new_count > mx:
            await r.decr(rkey)
            logger.info("[PatentHubBudget] key=%s 软超额 %d/%d，返前端二次确认",
                        key[:24], mx, mx)
            return (False, mx, mx)

        if force and new_count > mx:
            logger.info("[PatentHubBudget] key=%s 强制扣费 %d/%d（用户二次确认后越权）",
                        key[:24], new_count, mx)
        else:
            logger.info("[PatentHubBudget] key=%s 预扣成功 %d/%d", key[:24], new_count, mx)
        return (True, new_count, mx)
    finally:
        await r.aclose()


async def refund(key: str) -> None:
    """下载失败时回退计数（允许用户重试不扣费）。不会减到负数。"""
    r = await _redis()
    try:
        rkey = _redis_key(key)
        raw = await r.get(rkey)
        current = int(raw) if raw else 0
        if current > 0:
            await r.decr(rkey)
            logger.info("[PatentHubBudget] key=%s 已回退 %d→%d", key[:24], current, current - 1)
    finally:
        await r.aclose()
