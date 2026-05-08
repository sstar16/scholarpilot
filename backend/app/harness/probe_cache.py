"""
Probe cache — 跨提问/跨会话复用 section 级探针结果。

核心思想：
- 每次跑完探针（协作模式 / 深度提取）都把 {question, excerpts} 存到 doc.probe_cache
- 下一个问题先查缓存：若历史 question 的关键词与当前 question 高度重叠
  → 复用历史 excerpts，省一次 LLM 调用

匹配算法（简单版）：
- 从 question 抽 concepts（去停用词、取长度 ≥2 的 token）
- 对每条 cache 条目算 Jaccard(当前concepts, 历史concepts)
- 阈值 ≥ 0.5 视为命中

之所以不用 embedding：
- 项目内 embedding/pgvector 已被放弃（CLAUDE.md memory）
- 概念重叠对中文 + 英文学术问题已经够用，成本为零

未来升级方向：LLM 做一次"这些历史问题与当前问题是否等价"的批量判断，以替换 Jaccard。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.document import Document

logger = logging.getLogger(__name__)


MATCH_JACCARD_THRESHOLD = 0.15    # 概念重叠率阈值（n-gram 稀疏，阈值不宜过高）
MAX_CACHE_ENTRIES_PER_DOC = 30    # 每篇最多保留的 cache 条目
MAX_EXCERPTS_FROM_CACHE = 6       # 从单条 cache 条目最多复用的 excerpt 数


# 粗暴停用词表：不做稳定词形还原，仅剔除功能词
_STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "about",
    "as", "into", "like", "through", "after", "over", "between", "out",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "not", "no", "so", "than", "too", "very",
    "can", "will", "just", "should", "now", "also", "how", "why",
    "introduce", "discuss", "show", "tell", "explain",
}
_STOPWORDS_ZH = {
    "的", "了", "和", "与", "是", "在", "也", "有", "吗", "呢", "啊",
    "这", "那", "这些", "那些", "什么", "怎么", "为什么", "如何",
    "可以", "能够", "请", "帮我", "给我", "一下", "下",
}


def _normalize_concepts(text: str) -> set[str]:
    """把 question 转成标准化概念集合。"""
    if not text:
        return set()
    # 英文 token + 中文 token 分开抽
    # 英文：按空格/标点切，保留 ≥3 字母的 token
    en_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9\-_]{2,}", text.lower())
    en_tokens = [t for t in en_tokens if t not in _STOPWORDS_EN]
    # 中文：按 2-3 字滑窗（简单 n-gram）
    zh_only = re.sub(r"[a-zA-Z0-9\s]+", " ", text)
    zh_tokens: list[str] = []
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}", zh_only):
        seg = m.group(0)
        # 滑窗取 2-3 字
        for i in range(len(seg) - 1):
            tok = seg[i : i + 2]
            if tok not in _STOPWORDS_ZH:
                zh_tokens.append(tok)
            if i + 3 <= len(seg):
                tok3 = seg[i : i + 3]
                zh_tokens.append(tok3)
    return set(en_tokens) | set(zh_tokens)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def load_cached_excerpts(
    doc: Document,
    question: str,
    threshold: float = MATCH_JACCARD_THRESHOLD,
) -> Optional[List[dict]]:
    """
    若 doc.probe_cache 里有与当前 question 概念重叠 ≥ threshold 的历史条目
    → 返回其 excerpts；否则返回 None。

    多条命中取相似度最高的一条。
    """
    cache = doc.probe_cache or []
    if not cache:
        return None
    q_concepts = _normalize_concepts(question)
    if len(q_concepts) < 2:   # 问题太短时不启用缓存
        return None

    best_sim = 0.0
    best_entry: Optional[dict] = None
    for entry in cache:
        if not isinstance(entry, dict):
            continue
        hist_concepts = set(entry.get("question_concepts") or [])
        if not hist_concepts:
            continue
        sim = _jaccard(q_concepts, hist_concepts)
        if sim > best_sim:
            best_sim = sim
            best_entry = entry

    if best_entry is None or best_sim < threshold:
        return None

    excerpts = best_entry.get("excerpts") or []
    if not excerpts:
        return None

    logger.info(
        "[probe_cache] HIT doc=%s sim=%.2f reusing %d excerpts (hist_q=%r)",
        str(doc.id)[:8], best_sim, len(excerpts),
        (best_entry.get("question_hint") or "")[:60],
    )
    return excerpts[:MAX_EXCERPTS_FROM_CACHE]


async def save_to_cache(
    db: AsyncSession,
    doc: Document,
    question: str,
    excerpts: List[dict],
    source: str = "collaboration",
    adopted: bool = False,
    commit: bool = False,
) -> None:
    """把本次探针结果写入 doc.probe_cache。FIFO 裁剪。"""
    if not excerpts:
        return
    entry = {
        "question_hint": question[:300],
        "question_concepts": sorted(_normalize_concepts(question)),
        "excerpts": excerpts,
        "adopted": bool(adopted),
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    cache = list(doc.probe_cache or [])
    cache.append(entry)
    # FIFO 裁剪：超过上限丢最早的
    if len(cache) > MAX_CACHE_ENTRIES_PER_DOC:
        cache = cache[-MAX_CACHE_ENTRIES_PER_DOC:]
    doc.probe_cache = cache
    flag_modified(doc, "probe_cache")
    if commit:
        await db.commit()
    logger.info(
        "[probe_cache] SAVE doc=%s entries=%d new_excerpts=%d source=%s",
        str(doc.id)[:8], len(cache), len(excerpts), source,
    )


def mark_entry_adopted(
    doc: Document,
    question_hint: str,
) -> bool:
    """用户采纳某条历史探针结果（写入卡片/md时调用）。返回是否找到该条。"""
    cache = doc.probe_cache or []
    for entry in cache:
        if isinstance(entry, dict) and entry.get("question_hint") == question_hint:
            entry["adopted"] = True
            flag_modified(doc, "probe_cache")
            return True
    return False


def list_adopted_excerpts(doc: Document) -> List[dict]:
    """返回所有 adopted=True 条目的 excerpts（合并 + 去重），供 .md 生成使用。"""
    cache = doc.probe_cache or []
    out: list[dict] = []
    seen = set()
    for entry in cache:
        if not isinstance(entry, dict) or not entry.get("adopted"):
            continue
        for ex in entry.get("excerpts") or []:
            key = (ex.get("doc_id"), ex.get("section_idx"))
            if key in seen:
                continue
            seen.add(key)
            out.append(ex)
    return out
