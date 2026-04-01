"""
Trend Spotter Skill — identifies emerging research trends from accumulated results.

Available after round 3 (enough data accumulated).
Flow:
1. Collect all documents from rounds 1-N with publication dates
2. Count term frequency by year bucket
3. Identify terms with increasing trajectory
4. LLM generates a trend summary

LLM cost: ~1 call ($0.003)
"""
import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="trend_spotter",
    display_name="Trend Spotter",
    description="Identify emerging research trends from your search results",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id"],
    estimated_llm_calls=1,
    estimated_duration_seconds=10,
    min_round=3,
)


async def execute(context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute trend analysis across all completed rounds."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.round_document import RoundDocument
    from app.models.search_round import SearchRound

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            # 1. Collect all documents for this project
            docs_result = await db.execute(
                select(Document)
                .join(RoundDocument, RoundDocument.document_id == Document.id)
                .join(SearchRound, SearchRound.id == RoundDocument.round_id)
                .where(SearchRound.project_id == context["project_id"])
            )
            documents = docs_result.scalars().all()

            if len(documents) < 5:
                return {"error": "Not enough documents for trend analysis (need >= 5)"}

            # 2. Extract terms by year
            year_terms: Dict[int, Counter] = defaultdict(Counter)
            all_terms: Counter = Counter()

            for doc in documents:
                year = _extract_year(doc.publication_date)
                if not year:
                    continue

                # Use AI key points if available, else title words
                terms = []
                if doc.ai_key_points:
                    for kp in doc.ai_key_points:
                        terms.extend(kp.lower().split())
                elif doc.title:
                    terms = [w.lower() for w in doc.title.split() if len(w) > 3]

                for term in terms:
                    if len(term) > 2:
                        year_terms[year][term] += 1
                        all_terms[term] += 1

            # 3. Find rising trends (terms appearing more in recent years)
            sorted_years = sorted(year_terms.keys())
            if len(sorted_years) < 2:
                return {
                    "trends": [],
                    "top_terms": [t for t, _ in all_terms.most_common(20)],
                    "doc_count": len(documents),
                    "message": "Not enough year diversity for trend detection",
                }

            mid = len(sorted_years) // 2
            early_years = sorted_years[:mid]
            late_years = sorted_years[mid:]

            early_counts = Counter()
            late_counts = Counter()
            for y in early_years:
                early_counts.update(year_terms[y])
            for y in late_years:
                late_counts.update(year_terms[y])

            # Rising = appears more in late period than early
            rising = []
            for term, late_count in late_counts.most_common(50):
                early_count = early_counts.get(term, 0)
                if late_count > early_count and late_count >= 2:
                    rising.append({
                        "term": term,
                        "early_count": early_count,
                        "late_count": late_count,
                        "growth": late_count - early_count,
                    })

            rising.sort(key=lambda x: x["growth"], reverse=True)

            # 4. LLM summary (optional, only if LLM available)
            summary = None
            try:
                from app.services.core.llm_providers import LLMProviderManager
                from app.services.core.llm_config_store import load_llm_config
                llm = LLMProviderManager(default_ollama_host=settings.ollama_host)
                await load_llm_config(llm, settings.redis_url)

                top_rising = [r["term"] for r in rising[:10]]
                top_overall = [t for t, _ in all_terms.most_common(10)]
                prompt = (
                    f"Based on academic search results analysis:\n"
                    f"- Rising terms: {', '.join(top_rising)}\n"
                    f"- Most common terms: {', '.join(top_overall)}\n"
                    f"- Time range: {sorted_years[0]}-{sorted_years[-1]}\n\n"
                    "Write a 3-sentence research trend summary in Chinese. "
                    "Focus on emerging directions and potential opportunities."
                )
                summary = await llm.generate(prompt, temperature=0.3)
            except Exception as e:
                logger.warning("[TrendSpotter] LLM summary failed: %s", e)

            return {
                "rising_terms": rising[:15],
                "top_terms": [t for t, _ in all_terms.most_common(20)],
                "year_range": [sorted_years[0], sorted_years[-1]],
                "doc_count": len(documents),
                "summary": summary,
            }
    finally:
        await engine.dispose()


def _extract_year(date_str) -> int | None:
    """Extract year from various date formats."""
    if not date_str:
        return None
    try:
        s = str(date_str)[:4]
        y = int(s)
        if 1900 <= y <= 2100:
            return y
    except (ValueError, TypeError):
        pass
    return None
