"""
Quality Audit Skill — 评估项目文献库的完整性和健康度

逻辑（全本地，零 LLM 成本）：
1. 4 桶分布：是否偏科（比如 irrelevant 比例过高）
2. 数据源多样性：是否只从某一个源来
3. 时间覆盖：年份范围 + 空白年份
4. 作者/期刊多样性：是否过度集中
5. 有无 ai_summary / quality_score 缺失的文献
6. 给出 A-D 健康等级 + 改进建议
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="quality_audit",
    display_name="Quality Audit",
    description="评估项目文献库的完整性：桶分布、源多样性、时间覆盖、作者集中度",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id"],
    estimated_llm_calls=0,
    estimated_duration_seconds=3,
    min_round=1,
)


async def execute(context: Dict[str, Any]) -> Dict[str, Any]:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.document_classification import DocumentClassification
    from app.models.round_document import RoundDocument
    from app.models.search_round import SearchRound
    from app.models.project import Project

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            project = await db.get(Project, context["project_id"])
            if not project:
                return {"error": "Project not found"}

            # 所有 doc（来自 round + manual upload）
            r_ids_q = await db.execute(
                select(SearchRound.id).where(SearchRound.project_id == project.id)
            )
            round_ids = [r[0] for r in r_ids_q.all()]
            doc_ids: set = set()
            if round_ids:
                rd_q = await db.execute(
                    select(RoundDocument.document_id).where(
                        RoundDocument.round_id.in_(round_ids)
                    )
                )
                doc_ids.update(r[0] for r in rd_q.all())
            cls_q = await db.execute(
                select(DocumentClassification.document_id, DocumentClassification.bucket).where(
                    DocumentClassification.project_id == project.id
                )
            )
            cls_rows = cls_q.all()
            doc_ids.update(r[0] for r in cls_rows)

            if not doc_ids:
                return {"error": "项目下暂无文献", "grade": "N/A"}

            docs_q = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
            docs = list(docs_q.scalars().all())

            # Bucket dist
            bucket_counts: Counter = Counter(b for _d, b in cls_rows)
            total_classified = sum(bucket_counts.values())
            irrelevant_ratio = (
                bucket_counts.get("irrelevant", 0) / total_classified
                if total_classified else 0.0
            )

            # Source diversity
            source_counts: Counter = Counter(d.source or "unknown" for d in docs)
            dominant_source_ratio = (
                source_counts.most_common(1)[0][1] / len(docs) if docs else 0
            )

            # Time coverage
            years = [d.publication_date.year for d in docs if d.publication_date]
            year_range = (min(years), max(years)) if years else (None, None)
            this_year = datetime.now(timezone.utc).year
            has_recent = any(y >= this_year - 2 for y in years)

            # Author concentration
            author_counter: Counter = Counter()
            for d in docs:
                if d.authors:
                    first = d.authors.split(",")[0].split(";")[0].strip()
                    if first:
                        author_counter[first[:40]] += 1
            top_author_ratio = (
                author_counter.most_common(1)[0][1] / len(docs) if docs else 0
            )

            # Missing metadata
            missing_summary = sum(1 for d in docs if not d.ai_summary)
            missing_quality = sum(1 for d in docs if d.quality_score is None)

            issues: list[Dict[str, str]] = []
            if irrelevant_ratio > 0.4:
                issues.append({
                    "severity": "high",
                    "category": "bucket_imbalance",
                    "message": f"irrelevant 占比 {irrelevant_ratio:.0%}，可能检索关键词有误或画像偏离",
                })
            if dominant_source_ratio > 0.7 and len(docs) >= 6:
                issues.append({
                    "severity": "medium",
                    "category": "source_monoculture",
                    "message": f"超过 {dominant_source_ratio:.0%} 文献来自单一源，建议启用更多数据源",
                })
            if not has_recent and len(docs) >= 5:
                issues.append({
                    "severity": "medium",
                    "category": "time_gap",
                    "message": f"最近 2 年（{this_year - 1}+）无文献，可能遗漏最新进展",
                })
            if top_author_ratio > 0.4:
                issues.append({
                    "severity": "low",
                    "category": "author_concentration",
                    "message": "单一作者主导，可拓宽到其他研究团队",
                })
            if missing_summary / max(len(docs), 1) > 0.3:
                issues.append({
                    "severity": "low",
                    "category": "missing_summary",
                    "message": f"{missing_summary}/{len(docs)} 篇缺 AI 摘要",
                })

            # A-D grade
            grade = "A"
            if any(i["severity"] == "high" for i in issues):
                grade = "C"
            elif sum(1 for i in issues if i["severity"] == "medium") >= 2:
                grade = "C"
            elif any(i["severity"] == "medium" for i in issues):
                grade = "B"
            elif issues:
                grade = "B"

            return {
                "grade": grade,
                "issues": issues,
                "stats": {
                    "total_docs": len(docs),
                    "total_classified": total_classified,
                    "bucket_counts": dict(bucket_counts),
                    "sources": dict(source_counts),
                    "year_range": year_range,
                    "top_authors": dict(author_counter.most_common(5)),
                    "missing_summary": missing_summary,
                    "missing_quality": missing_quality,
                },
            }
    finally:
        await engine.dispose()
