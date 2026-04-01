"""
Deep Dive Skill — when a user marks a paper as "very relevant" (relevance=2),
automatically find closely related work.

Flow:
1. Extract key concepts from the anchor paper's ai_key_points
2. Build a focused query from those concepts
3. Search via high-reliability tools (OpenAlex, Crossref, arXiv)
4. Return top-5 related papers

LLM cost: ~1 call ($0.003 with DeepSeek)
"""
import logging
from typing import Any, Dict, List

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="deep_dive",
    display_name="Deep Dive",
    description="Find related work for a highly-rated paper",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id", "document_id"],
    estimated_llm_calls=1,
    estimated_duration_seconds=15,
    min_round=1,
)


async def execute(context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the deep dive skill."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.project import Project

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            # 1. Load anchor document
            doc_result = await db.execute(
                select(Document).where(Document.id == context["document_id"])
            )
            doc = doc_result.scalar_one_or_none()
            if not doc:
                return {"error": "Document not found"}

            # Load project for description context
            project_result = await db.execute(
                select(Project).where(Project.id == context["project_id"])
            )
            project = project_result.scalar_one_or_none()

            # 2. Build focused query from key points + title
            key_points = doc.ai_key_points or []
            concepts = " ".join(key_points[:3]) if key_points else (doc.abstract or doc.title or "")[:200]
            query = f"{doc.title or ''} {concepts}"[:300]

            # 3. Search via reliable tools
            from app.services.fetchers.international import ALL_FETCHERS
            reliable_sources = ["openalex", "crossref", "arxiv", "europe_pmc"]
            related_docs: List[Dict] = []

            import asyncio
            tasks = []
            for src_id in reliable_sources:
                fetcher = ALL_FETCHERS.get(src_id)
                if fetcher:
                    tasks.append(fetcher.safe_fetch(query=query, max_results=5))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, tuple):
                        _, docs = result
                        related_docs.extend(docs)

            # 4. Deduplicate and rank by title similarity to anchor
            seen_titles = {doc.title.lower() if doc.title else ""}
            unique_docs = []
            for d in related_docs:
                title_lower = (d.get("title") or "").lower()
                if title_lower and title_lower not in seen_titles:
                    seen_titles.add(title_lower)
                    unique_docs.append(d)

            # Simple relevance: prefer docs with more key_point terms in abstract
            if key_points:
                kp_terms = set()
                for kp in key_points:
                    kp_terms.update(kp.lower().split())
                for d in unique_docs:
                    abstract_lower = (d.get("abstract") or "").lower()
                    d["_relevance"] = sum(1 for t in kp_terms if t in abstract_lower)
                unique_docs.sort(key=lambda x: x.get("_relevance", 0), reverse=True)

            top_5 = unique_docs[:5]
            # Clean up internal fields
            for d in top_5:
                d.pop("_relevance", None)

            return {
                "anchor_title": doc.title,
                "related_papers": top_5,
                "total_found": len(related_docs),
                "query_used": query[:200],
            }
    finally:
        await engine.dispose()
