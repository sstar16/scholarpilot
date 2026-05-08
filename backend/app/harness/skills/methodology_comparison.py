"""
Methodology Comparison Skill — 对比项目文献里用了哪些方法/技术路线

逻辑：
1. 扫描高相关文献的 concept_tags + ai_key_points
2. 规则提取"方法/技术/实验"类关键词（包括"方法"、"算法"、"RNA-seq"、"CNN"等）
3. 统计分布，LLM 输出对比结论（各家方法的异同与优劣）

LLM 成本：~1 call ($0.003)
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="methodology_comparison",
    display_name="Methodology Comparison",
    description="对比项目文献中使用的主流方法/技术路线及其异同",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id"],
    estimated_llm_calls=1,
    estimated_duration_seconds=10,
    min_round=2,
)

# 简化的"方法/技术"关键词白名单；命中任一词就视为方法
_METHOD_HINTS = (
    "method", "algorithm", "model", "framework", "approach", "technique",
    "CNN", "RNN", "LSTM", "transformer", "GAN", "BERT", "GPT",
    "RNA-seq", "PCR", "CRISPR", "sc-RNA", "ChIP-seq", "Western blot",
    "方法", "算法", "模型", "框架", "技术", "实验", "检测",
    "显微", "测序", "荧光", "合成",
)


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
                        ["very_relevant", "relevant"]
                    ),
                )
            )
            docs = list(q.scalars().all())
            if len(docs) < 2:
                return {"error": "至少需要 2 篇 very_relevant / relevant 文献"}

            method_counter: Counter = Counter()
            for doc in docs:
                candidates = []
                if doc.concept_tags:
                    candidates.extend(doc.concept_tags)
                if doc.ai_key_points:
                    for kp in doc.ai_key_points:
                        candidates.append(str(kp))
                for c in candidates:
                    low = c.lower()
                    if any(h.lower() in low for h in _METHOD_HINTS):
                        method_counter[c[:40]] += 1

            top_methods = method_counter.most_common(12)
            summary = None
            if top_methods:
                try:
                    from app.services.core.llm_config_store import get_llm_manager
                    llm = await get_llm_manager()
                    methods_str = ", ".join(f"{m} (×{n})" for m, n in top_methods)
                    prompt = (
                        f"项目方向：{(project.description or '')[:200]}\n\n"
                        f"项目文献中出现的方法/技术：{methods_str}\n\n"
                        "用中文 4 句话对比这些方法的技术路线与应用场景差异，"
                        "并指出哪一种在本项目场景最主流。"
                    )
                    summary = await llm.generate(prompt, temperature=0.3)
                except Exception as e:
                    logger.warning("[method_cmp] LLM summary failed: %s", e)

            return {
                "top_methods": [
                    {"method": m, "count": n} for m, n in top_methods
                ],
                "doc_analyzed": len(docs),
                "summary": summary,
            }
    finally:
        await engine.dispose()
