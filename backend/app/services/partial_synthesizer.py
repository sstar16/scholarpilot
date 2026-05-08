"""Answer Now: 基于已有部分检索/评分结果, LLM 快速合成 best-effort 答案.

设计要点:
- Redis flag 由 API 路由设置, Celery worker 在 stage 边界检测.
- LLM/Redis 失败永远不能让 round 炸 —— 任何异常都吞成结构化 error 字典.
- prompt 显式告知 LLM 这是 partial 结果, 鼓励诚实标注信息缺口.
- max_docs 截断保护, 文献再多也不让 prompt 失控.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Redis key 前缀, 与现有 keyword_plan:* / patenthub:pdf_budget:* 保持同风格
INTERRUPT_KEY_PREFIX = "answer_now:"
DEFAULT_FLAG_TTL_SECONDS = 300  # 5min, 够走完任意一个 stage 边界


# ----------------------------------------------------------------------------
# Redis flag (API ↔ Worker 之间的中断信号)
# ----------------------------------------------------------------------------

async def is_interrupt_requested(round_id: str, redis_client) -> bool:
    """检查 Redis 中断 flag.

    redis_client 形如 ``redis.asyncio.Redis`` —— 与 search_tasks.py 中
    `aioredis.from_url(settings.redis_url)` 保持一致.

    异常防御: redis 挂掉返回 False, 让主流程继续, 不阻塞用户.
    """
    if not round_id:
        return False
    try:
        raw = await redis_client.get(f"{INTERRUPT_KEY_PREFIX}{round_id}")
    except Exception as e:
        logger.warning("[answer_now] is_interrupt_requested redis error: %s", e)
        return False
    return bool(raw)


async def set_interrupt_flag(
    round_id: str,
    redis_client,
    ttl_seconds: int = DEFAULT_FLAG_TTL_SECONDS,
) -> bool:
    """设置中断 flag, 由 API 路由调用.

    返回 True 表示成功写入; False 表示 redis 异常 —— 上层应当还能继续走
    (worker 自己即将到达 stage 边界时再读不到 flag, 顶多就是 partial 不
    会触发, 不影响主流程).
    """
    if not round_id:
        return False
    try:
        await redis_client.set(
            f"{INTERRUPT_KEY_PREFIX}{round_id}",
            "1",
            ex=ttl_seconds,
        )
        return True
    except Exception as e:
        logger.warning("[answer_now] set_interrupt_flag redis error: %s", e)
        return False


async def clear_interrupt_flag(round_id: str, redis_client) -> None:
    """清除 flag, partial 答案生成完后调用 (避免被旧 flag 重复触发)."""
    if not round_id:
        return
    try:
        await redis_client.delete(f"{INTERRUPT_KEY_PREFIX}{round_id}")
    except Exception as e:
        logger.warning("[answer_now] clear_interrupt_flag redis error: %s", e)


# ----------------------------------------------------------------------------
# 核心: synthesize_partial
# ----------------------------------------------------------------------------

async def synthesize_partial(
    round_id: str,
    project_description: str,
    docs_so_far: list[dict],
    current_stage: str,
    llm_manager,
    *,
    max_docs: int = 30,
) -> dict:
    """基于已有文献快速合成答案.

    Args:
        round_id: 用于日志/调试
        project_description: 用户的研究方向描述
        docs_so_far: 当前阶段已检索/评分到的文献 dict 列表
        current_stage: 触发中断时的 stage 名 (searching/scoring/saving/summarizing)
        llm_manager: ``LLMProviderManager`` 实例
        max_docs: prompt 安全截断 (默认 30 篇)

    Returns:
        dict, 形如::

            {
                "answer_markdown": str,
                "doc_ids_cited": list[str],
                "partial": True,
                "interrupted_at_stage": current_stage,
                "doc_count_used": int,
                "confidence": float,    # 0-1
                "disclaimer": str,
                "error": str | None,    # 只在异常路径填
            }

    LLM/任何异常都不会向上抛 —— 上层 worker 不能因 partial 失败而挂.
    """
    docs = list(docs_so_far or [])[:max_docs]
    doc_count = len(docs)

    # ------------------------------------------------------------------
    # Edge case: 完全没文献 —— 直接降级返回 disclaimer, 不调 LLM
    # ------------------------------------------------------------------
    if doc_count == 0:
        disclaimer = (
            f"在 {current_stage} 阶段中断时还没有任何文献入手, "
            "无法基于已有证据合成答案. 建议等待检索完成或重启一轮."
        )
        return {
            "answer_markdown": (
                "## 喵呜 还没拿到一篇文献\n\n"
                f"在 **{current_stage}** 阶段被中断, 此刻 0 篇候选可用. "
                "可以等当前轮跑完, 或者重新发起检索时换更宽松的关键词.\n"
            ),
            "doc_ids_cited": [],
            "partial": True,
            "interrupted_at_stage": current_stage,
            "doc_count_used": 0,
            "confidence": 0.0,
            "disclaimer": disclaimer,
            "error": None,
        }

    # ------------------------------------------------------------------
    # 构造 prompt + 调 LLM
    # ------------------------------------------------------------------
    prompt = _build_partial_prompt(project_description, docs, current_stage)

    try:
        raw = await llm_manager.generate(
            prompt,
            temperature=0.3,
            max_tokens=4096,
        )
    except Exception as e:
        logger.exception("[answer_now] LLM 调用失败 round=%s: %s", round_id[:8], e)
        return _llm_error_payload(current_stage, doc_count, str(e))

    if not raw or not raw.strip():
        logger.warning(
            "[answer_now] LLM 返回空 round=%s stage=%s docs=%d",
            round_id[:8], current_stage, doc_count,
        )
        return _llm_error_payload(current_stage, doc_count, "LLM 返回空内容")

    # ------------------------------------------------------------------
    # 简单引用提取: prompt 让 LLM 用 [doc:<id>] 形式标注, 这里 grep 出来
    # ------------------------------------------------------------------
    doc_ids_cited = _extract_cited_doc_ids(raw, docs)

    # confidence 启发式: doc_count / 10 截断到 [0.1, 0.9]
    # —— 不到 5 篇视为低置信; 30 篇 (max_docs 上限) 也只到 0.9 (因为是 partial)
    confidence = max(0.1, min(0.9, doc_count / 10.0))

    disclaimer = (
        f"⚠️ 这是 **Answer Now 部分结果** —— 在 `{current_stage}` 阶段中断, "
        f"基于 {doc_count} 篇已有文献合成. 建议等本轮跑完看完整摘要库."
    )

    return {
        "answer_markdown": raw.strip(),
        "doc_ids_cited": doc_ids_cited,
        "partial": True,
        "interrupted_at_stage": current_stage,
        "doc_count_used": doc_count,
        "confidence": confidence,
        "disclaimer": disclaimer,
        "error": None,
    }


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _build_partial_prompt(
    project_description: str,
    docs: list[dict],
    current_stage: str,
) -> str:
    """构造 Answer Now 的 prompt.

    关键词 (供 test 校验): "Answer Now", "部分结果", "partial", current_stage.
    """
    bullets = []
    for i, d in enumerate(docs, start=1):
        title = (d.get("title") or "").strip().replace("\n", " ")
        abstract = (d.get("abstract") or "").strip().replace("\n", " ")
        # 摘要截 600 字, 防止 prompt 过长
        if len(abstract) > 600:
            abstract = abstract[:600] + "..."
        ext_id = (
            d.get("external_id")
            or d.get("doi")
            or d.get("id")
            or f"d{i}"
        )
        source = d.get("source") or "?"
        bullets.append(
            f"[doc:{ext_id}] ({source}) {title}\n摘要: {abstract or '（无摘要）'}"
        )
    docs_block = "\n\n".join(bullets) if bullets else "（无文献）"

    return (
        "你是 ScholarPilot 的科研助理. 用户在 Answer Now 快通道下点击了"
        f' "先看现有结果", 当前轮在 `{current_stage}` 阶段被中断.\n\n'
        "## 任务\n"
        "基于下方已检索到的部分文献, 用中文 Markdown 合成一份 best-effort 部分结果. "
        "明确告诉用户: 这是 partial 结果, 文献数量有限. 给出谨慎的综合,"
        "不要编造未提供的文献.\n\n"
        "## 输出要求\n"
        "1. 结构化 Markdown: ## 标题, 关键发现, 局限与下一步.\n"
        "2. 引用文献时使用 [doc:<external_id>] 形式 (内联在句末), "
        "external_id 从下方文献块抄. 不要自创 ID.\n"
        "3. 第一句必须是醒目的 disclaimer, 标明 partial / 部分结果 / "
        f"中断阶段=`{current_stage}`.\n"
        "4. 控制在 800 字以内, 不要无意义堆砌.\n\n"
        f"## 用户研究方向\n{project_description}\n\n"
        f"## 当前已有文献 ({len(docs)} 篇)\n{docs_block}\n"
    )


def _extract_cited_doc_ids(answer: str, docs: list[dict]) -> list[str]:
    """从 LLM 输出中粗略抓取 [doc:xxx] 引用, 校验后返回去重 list."""
    import re

    valid_ids = set()
    for d in docs:
        for k in ("external_id", "doi", "id"):
            v = d.get(k)
            if v:
                valid_ids.add(str(v))

    cited: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"\[doc:([^\]\s]+)\]", answer or ""):
        cid = m.group(1).strip()
        if cid in valid_ids and cid not in seen:
            cited.append(cid)
            seen.add(cid)
    return cited


def _llm_error_payload(stage: str, doc_count: int, err_msg: str) -> dict:
    """LLM 失败时返回的结构化 payload (上层不抛)."""
    return {
        "answer_markdown": (
            "## 喵 这次合成失败了\n\n"
            f"在 **{stage}** 阶段尝试生成 partial 答案时 LLM 出错: "
            f"`{err_msg[:160]}`.\n\n"
            f"已有 {doc_count} 篇文献被收集, 你可以等本轮跑完, 或者"
            "稍后再试一次 Answer Now."
        ),
        "doc_ids_cited": [],
        "partial": True,
        "interrupted_at_stage": stage,
        "doc_count_used": doc_count,
        "confidence": 0.0,
        "disclaimer": "Answer Now LLM 调用失败, 这是降级返回.",
        "error": err_msg[:500],
    }
