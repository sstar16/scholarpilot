"""
Citation Network Skill — 分析项目文献的引用关系，找出"必读核心"

逻辑：
1. 扫描所有高相关文档 (bucket=very_relevant + relevant)
2. 从 ai_key_points 和 ai_summary 里提取被引文献特征（作者名 + 年份）
3. 统计被引频率，Top N 即"绕不过的核心文献"
4. LLM 概括核心文献的共性（可选，低 temperature）

LLM 成本：~1 call ($0.003) 摘要步骤；规则部分零成本。
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="citation_network",
    display_name="Citation Network",
    description="分析项目文献的引用关系，找出不可绕过的核心参考文献",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id"],
    estimated_llm_calls=1,
    estimated_duration_seconds=8,
    min_round=2,
)

# 形如 "Smith et al., 2021" / "Wang 2020" / "Zhou, 2019" 的简化引用模式
_CITE_PATTERNS = [
    re.compile(r"([A-Z][a-z]+)(?:\s+et al\.?)?[\s,]+(\d{4})"),
    re.compile(r"([\u4e00-\u9fa5]{1,3})(?:等)?(?:,|，)?\s*(\d{4})"),  # 中文 "李等，2021"
]


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
                select(Document, DocumentClassification.bucket)
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
            rows = list(q.all())
            if len(rows) < 2:
                return {"error": "需要至少 2 篇 very_relevant / relevant 文献才能分析引用网络"}

            citations = Counter()
            for doc, _bucket in rows:
                text = _extractable_text(doc)
                for pat in _CITE_PATTERNS:
                    for author, year in pat.findall(text):
                        cite = f"{author.strip()} {year}"
                        citations[cite] += 1

            top_citations = citations.most_common(15)

            summary = None
            if top_citations:
                try:
                    from app.services.core.llm_config_store import get_llm_manager
                    llm = await get_llm_manager()
                    cite_str = ", ".join(f"{c} (×{n})" for c, n in top_citations[:8])
                    prompt = (
                        f"项目：{(project.description or '')[:200]}\n\n"
                        f"高频被引条目：{cite_str}\n\n"
                        "用中文 3 句话概括这些核心文献的共性（方法/流派/时代）。"
                    )
                    summary = await llm.generate(prompt, temperature=0.3)
                except Exception as e:
                    logger.warning("[citation_network] LLM summary failed: %s", e)

            return {
                "top_citations": [
                    {"citation": c, "count": n} for c, n in top_citations
                ],
                "doc_analyzed": len(rows),
                "summary": summary,
            }
    finally:
        await engine.dispose()


def _extractable_text(doc) -> str:
    parts: List[str] = []
    if doc.ai_summary:
        parts.append(doc.ai_summary)
    if doc.ai_key_points:
        parts.extend(str(kp) for kp in doc.ai_key_points)
    if doc.abstract:
        parts.append(doc.abstract)
    return "\n".join(parts)
