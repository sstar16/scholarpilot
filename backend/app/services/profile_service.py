"""
用户偏好画像服务
Phase 1: 基于关键词统计的偏好模型（jieba TF-IDF 中文 + 正则英文）
Phase 2: 叠加 embedding 向量
"""
import re
from collections import Counter
from typing import List, Optional, Dict
from datetime import datetime, timezone
import jieba
import jieba.analyse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user_profile import UserProfile
from app.models.feedback import Feedback
from app.models.document import Document
from app.services.llm_summarizer import LLMSummarizer


STOP_WORDS = {
    "the", "a", "an", "and", "or", "in", "of", "to", "for", "with", "is",
    "are", "was", "were", "study", "analysis", "clinical", "trial", "research",
    "的", "了", "在", "是", "和", "与", "对", "中", "为", "等", "研究", "分析",
}


async def get_or_create_profile(
    user_id,
    project_id,
    db: AsyncSession,
) -> UserProfile:
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id == user_id,
            UserProfile.project_id == project_id,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = UserProfile(
            user_id=user_id,
            project_id=project_id,
            preferred_keywords=[],
            excluded_keywords=[],
            preferred_sources=[],
            preferred_doc_types=[],
            preferred_authors=[],
            feedback_count=0,
        )
        db.add(profile)
        await db.flush()
    return profile


async def update_profile_from_feedbacks(
    user_id,
    project_id,
    feedbacks: List[Dict],  # [{document_id, relevance, reason, positive_signals, negative_signals, document}]
    db: AsyncSession,
) -> UserProfile:
    """
    根据一批反馈更新用户画像
    """
    profile = await get_or_create_profile(user_id, project_id, db)

    # 统计关键词频次
    pos_kw_counter: Counter = Counter(profile.preferred_keywords or [])
    neg_kw_counter: Counter = Counter(profile.excluded_keywords or [])
    source_counter: Counter = Counter(profile.preferred_sources or [])

    for fb in feedbacks:
        doc = fb.get("document")
        relevance = fb.get("relevance", 0)

        # 正向反馈（相关/非常相关）
        if relevance >= 1 and doc:
            # 从标题/摘要提取关键词
            keywords = _extract_keywords(
                f"{doc.get('title', '')} {doc.get('abstract', '') or ''}"
            )
            weight = 2 if relevance == 2 else 1
            for kw in keywords:
                pos_kw_counter[kw] += weight

            # ai_key_points：LLM 已提取的领域精准词，权重 ×3（质量远高于正则）
            for point in (doc.get("ai_key_points") or []):
                for kw in _extract_keywords(point):
                    pos_kw_counter[kw] += weight * 3

            # 记录来源偏好
            if doc.get("source"):
                source_counter[doc["source"]] += weight

            # LLM 提取的正向信号
            for signal in (fb.get("positive_signals") or []):
                signal_kws = _extract_keywords(signal)
                for kw in signal_kws:
                    pos_kw_counter[kw] += 1

        # 负向反馈
        elif relevance == -1 and doc:
            keywords = _extract_keywords(
                f"{doc.get('title', '')} {doc.get('abstract', '') or ''}"
            )
            # 负向只统计低频正向词
            for kw in keywords:
                if pos_kw_counter.get(kw, 0) == 0:
                    neg_kw_counter[kw] += 1

            for signal in (fb.get("negative_signals") or []):
                signal_kws = _extract_keywords(signal)
                for kw in signal_kws:
                    neg_kw_counter[kw] += 1

    # 取 top-20 偏好关键词（排除出现在负向中的）
    neg_set = {kw for kw, cnt in neg_kw_counter.most_common(50)}
    preferred = [kw for kw, _ in pos_kw_counter.most_common(30) if kw not in neg_set][:20]
    excluded = [kw for kw, _ in neg_kw_counter.most_common(10)][:10]
    preferred_sources = [src for src, _ in source_counter.most_common(5)]

    profile.preferred_keywords = preferred
    profile.excluded_keywords = excluded
    profile.preferred_sources = preferred_sources
    profile.feedback_count += len(feedbacks)
    profile.last_updated = datetime.now(timezone.utc)

    await db.flush()
    return profile


def _extract_keywords(text: str) -> List[str]:
    """从文本提取有意义的关键词：中文用 jieba TF-IDF，英文用正则"""
    if not text:
        return []
    results = []
    seen = set()

    # 中文段落：jieba TF-IDF，比正则切词更准确
    cn_chunks = re.findall(r'[\u4e00-\u9fff，。、；：！？\s]+', text)
    if cn_chunks:
        cn_text = " ".join(cn_chunks)
        cn_kws = jieba.analyse.extract_tags(cn_text, topK=10, withWeight=False)
        for w in cn_kws:
            if w not in STOP_WORDS and w not in seen:
                results.append(w)
                seen.add(w)

    # 英文段落：支持连字符词（machine-learning），最少 3 字符
    en_words = re.findall(r'\b[a-zA-Z]{2,}(?:-[a-zA-Z]+)*\b', text)
    for w in en_words:
        wl = w.lower()
        if wl not in STOP_WORDS and len(wl) >= 3 and wl not in seen:
            results.append(wl)
            seen.add(wl)

    return results[:20]


async def get_profile_summary(profile: UserProfile) -> Dict:
    """返回人类可读的画像摘要"""
    return {
        "feedback_count": profile.feedback_count,
        "preferred_keywords": (profile.preferred_keywords or [])[:10],
        "excluded_keywords": (profile.excluded_keywords or [])[:5],
        "preferred_sources": profile.preferred_sources or [],
        "last_updated": profile.last_updated.isoformat() if profile.last_updated else None,
    }
