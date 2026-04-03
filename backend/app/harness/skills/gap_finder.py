"""
Gap Finder Skill — identifies potential research gaps from user feedback patterns.

Available after the final round or on manual invocation.
Flow:
1. Analyze feedback: topics with many "irrelevant" marks = oversaturated areas
2. Topics searched but with no highly-rated results = potential gaps
3. Cross-reference with user profile
4. LLM suggests research gaps

LLM cost: ~1 call ($0.003)
"""
import logging
from collections import Counter
from typing import Any, Dict, List

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="gap_finder",
    display_name="Gap Finder",
    description="Identify research gaps from your feedback patterns",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id"],
    estimated_llm_calls=1,
    estimated_duration_seconds=10,
    min_round=3,
)


async def execute(context: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze feedback patterns to find research gaps."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.feedback import Feedback
    from app.models.search_round import SearchRound
    from app.models.project import Project

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            # Load project
            project_result = await db.execute(
                select(Project).where(Project.id == context["project_id"])
            )
            project = project_result.scalar_one_or_none()
            if not project:
                return {"error": "Project not found"}

            # Load all feedback for this project
            feedbacks = await db.execute(
                select(Feedback, Document)
                .join(Document, Feedback.document_id == Document.id)
                .where(Feedback.project_id == context["project_id"])
            )
            rows = feedbacks.all()

            if len(rows) < 3:
                return {"error": "Not enough feedback for gap analysis (need >= 3)"}

            # Categorize by relevance
            positive_terms = Counter()   # Terms from relevant docs
            negative_terms = Counter()   # Terms from irrelevant docs
            all_sources = Counter()      # Sources used
            positive_sources = Counter() # Sources with good results

            for feedback, doc in rows:
                terms = _extract_terms(doc)
                all_sources[doc.source] += 1

                if feedback.relevance >= 1:
                    for t in terms:
                        positive_terms[t] += 1
                    positive_sources[doc.source] += 1
                elif feedback.relevance == -1:
                    for t in terms:
                        negative_terms[t] += 1

            # Gap indicators:
            # 1. Terms appearing in negative but NOT in positive = user wants but can't find
            gaps_by_terms = []
            for term, neg_count in negative_terms.most_common(30):
                pos_count = positive_terms.get(term, 0)
                if pos_count == 0 and neg_count >= 2:
                    gaps_by_terms.append({"term": term, "negative_mentions": neg_count})

            # 2. Sources with low positive rate = may need better queries for those
            source_gaps = []
            for src, total in all_sources.most_common():
                pos = positive_sources.get(src, 0)
                if total >= 3 and pos / total < 0.3:
                    source_gaps.append({
                        "source": src,
                        "total": total,
                        "positive": pos,
                        "hit_rate": round(pos / total, 2),
                    })

            # 3. LLM gap analysis
            summary = None
            try:
                from app.services.core.llm_config_store import get_llm_manager
                llm = await get_llm_manager()

                top_positive = [t for t, _ in positive_terms.most_common(10)]
                top_negative = [t for t, _ in negative_terms.most_common(10)]
                prompt = (
                    f"Research project: {project.description[:200]}\n\n"
                    f"User found these topics RELEVANT: {', '.join(top_positive)}\n"
                    f"User found these topics NOT relevant: {', '.join(top_negative)}\n"
                    f"Gap indicators (searched but not found relevant): "
                    f"{', '.join(g['term'] for g in gaps_by_terms[:5])}\n\n"
                    "Based on this feedback pattern, identify 2-3 potential research gaps "
                    "or underexplored directions. Write in Chinese, 3-4 sentences."
                )
                summary = await llm.generate(prompt, temperature=0.3)
            except Exception as e:
                logger.warning("[GapFinder] LLM analysis failed: %s", e)

            return {
                "term_gaps": gaps_by_terms[:10],
                "source_performance": source_gaps,
                "positive_focus": [t for t, _ in positive_terms.most_common(15)],
                "negative_focus": [t for t, _ in negative_terms.most_common(15)],
                "total_feedback": len(rows),
                "summary": summary,
            }
    finally:
        await engine.dispose()


def _extract_terms(doc) -> List[str]:
    """Extract meaningful terms from a document."""
    terms = []
    if doc.ai_key_points:
        for kp in doc.ai_key_points:
            terms.extend(kp.lower().split())
    elif doc.title:
        terms = [w.lower() for w in doc.title.split() if len(w) > 3]
    return [t for t in terms if len(t) > 2]
