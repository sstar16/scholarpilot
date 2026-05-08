"""
Emerging Topics Skill — 识别"冉冉升起"的新热点

逻辑：
1. 以 3 年为窗口（近 3 年 vs 前 3 年）对比 concept_tags 分布
2. 新窗口频率 / 旧窗口频率 > 阈值 = 升起的热点
3. 仅看新窗口有、旧窗口没有 = 全新主题
4. LLM 解读前 5 个上升主题

LLM 成本：~1 call ($0.003)
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="emerging_topics",
    display_name="Emerging Topics",
    description="基于发表年份对比，识别项目领域的新兴热点",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id"],
    estimated_llm_calls=1,
    estimated_duration_seconds=8,
    min_round=2,
)

WINDOW_YEARS = 3


async def execute(context: Dict[str, Any]) -> Dict[str, Any]:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.document_classification import DocumentClassification
    from app.models.project import Project

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            project = await db.get(Project, context["project_id"])
            if not project:
                return {"error": "Project not found"}

            q = await db.execute(
                select(Document)
                .join(
                    DocumentClassification,
                    DocumentClassification.document_id == Document.id,
                )
                .where(
                    DocumentClassification.project_id == context["project_id"],
                    DocumentClassification.bucket.in_(
                        ["very_relevant", "relevant", "uncertain"]
                    ),
                )
            )
            docs = list(q.scalars().all())
            if len(docs) < 4:
                return {"error": "至少需要 4 篇分类文献才能做时间对比"}

            current_year = datetime.now(timezone.utc).year
            recent_cutoff = current_year - WINDOW_YEARS
            older_cutoff = recent_cutoff - WINDOW_YEARS

            recent_tags: Counter = Counter()
            older_tags: Counter = Counter()
            for doc in docs:
                if not doc.concept_tags or not doc.publication_date:
                    continue
                year = doc.publication_date.year
                bucket = None
                if year > recent_cutoff:
                    bucket = recent_tags
                elif year > older_cutoff:
                    bucket = older_tags
                if bucket is not None:
                    for t in doc.concept_tags[:15]:
                        bucket[str(t)[:40]] += 1

            rising: list[Dict[str, Any]] = []
            brand_new: list[str] = []
            for tag, recent_n in recent_tags.most_common(40):
                older_n = older_tags.get(tag, 0)
                if older_n == 0 and recent_n >= 2:
                    brand_new.append(tag)
                elif recent_n / max(older_n, 1) >= 1.5 and recent_n >= 2:
                    rising.append({
                        "topic": tag,
                        "recent": recent_n,
                        "older": older_n,
                        "ratio": round(recent_n / max(older_n, 1), 2),
                    })

            summary = None
            items = rising[:5] + [{"topic": t, "recent": recent_tags[t], "older": 0, "ratio": 0.0} for t in brand_new[:3]]
            if items:
                try:
                    from app.services.core.llm_config_store import get_llm_manager
                    llm = await get_llm_manager()
                    items_str = ", ".join(f"{i['topic']} (↑{i['ratio']}x)" for i in items[:6])
                    prompt = (
                        f"项目方向：{(project.description or '')[:200]}\n\n"
                        f"近 {WINDOW_YEARS} 年涌现的主题：{items_str}\n\n"
                        "用中文 3 句话解释这些新兴方向的科学含义，并指出"
                        "最值得关注的 1-2 个方向及其潜在价值。"
                    )
                    summary = await llm.generate(prompt, temperature=0.3)
                except Exception as e:
                    logger.warning("[emerging_topics] LLM summary failed: %s", e)

            return {
                "rising_topics": rising[:10],
                "brand_new": brand_new[:10],
                "window_years": WINDOW_YEARS,
                "recent_doc_count": sum(1 for d in docs if d.publication_date and d.publication_date.year > recent_cutoff),
                "older_doc_count": sum(1 for d in docs if d.publication_date and d.publication_date.year <= recent_cutoff),
                "summary": summary,
            }
    finally:
        await engine.dispose()
