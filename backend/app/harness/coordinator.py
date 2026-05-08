"""
Multi-Agent Coordinator — orchestrates parallel agent tasks.

Adapted from Claude Code's S11 (Autonomous Agents / Coordinator Mode).

Three concurrent agent "lanes" run after search results are collected:
1. Summary Agent — generates AI summaries (existing, promoted to agent)
2. Quality Agent — evaluates result quality and suggests strategy adjustments
3. Profile Agent — pre-analyzes results for profile learning opportunities

All three run as parallel Celery tasks via a chord.
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class QualityAgent:
    """
    Evaluates search result quality and suggests improvements.
    Runs in parallel with summary generation.
    """

    async def evaluate(
        self,
        docs: List[Dict],
        query_plan_info: Dict,
        project_description: str,
        llm_manager=None,
    ) -> Dict[str, Any]:
        """
        Assess quality of search results and suggest improvements for next round.
        """
        if not docs:
            return {"quality_score": 0, "suggestions": ["No results found"]}

        # Compute basic quality metrics
        has_abstract = sum(1 for d in docs if d.get("abstract"))
        has_doi = sum(1 for d in docs if d.get("doi"))
        avg_citations = sum(d.get("citation_count", 0) for d in docs) / len(docs)
        source_diversity = len(set(d.get("source", "") for d in docs))

        metrics = {
            "total_docs": len(docs),
            "with_abstract": has_abstract,
            "with_doi": has_doi,
            "avg_citations": round(avg_citations, 1),
            "source_diversity": source_diversity,
            "abstract_rate": round(has_abstract / len(docs) * 100, 1),
        }

        # LLM quality assessment (optional)
        quality_summary = None
        if llm_manager and len(docs) >= 3:
            try:
                sample_titles = [d.get("title", "")[:80] for d in docs[:10]]
                prompt = (
                    f"Research topic: {project_description[:150]}\n"
                    f"Search returned {len(docs)} papers. Sample titles:\n"
                    + "\n".join(f"- {t}" for t in sample_titles)
                    + f"\n\nMetrics: {json.dumps(metrics)}\n\n"
                    "Rate search quality 1-10 and suggest 1-2 improvements for next round. "
                    "Reply in Chinese, 2-3 sentences."
                )
                quality_summary = await llm_manager.generate(prompt, temperature=0.2)
            except Exception as e:
                logger.warning("[QualityAgent] LLM assessment failed: %s", e)

        return {
            "metrics": metrics,
            "quality_summary": quality_summary,
            "suggestions": self._generate_suggestions(metrics),
        }

    def _generate_suggestions(self, metrics: Dict) -> List[str]:
        suggestions = []
        if metrics["abstract_rate"] < 50:
            suggestions.append("低摘要率 — 考虑增加 OpenAlex/EuropePMC 权重（摘要最完整）")
        if metrics["avg_citations"] < 5:
            suggestions.append("平均引用较低 — 可提高 citation_weight 或缩短时间范围")
        if metrics["source_diversity"] < 3:
            suggestions.append("数据源单一 — 下一轮尝试更多数据源")
        return suggestions


class ProfilePreAnalyzer:
    """
    Pre-analyzes search results to extract potential profile learning signals
    BEFORE user feedback. This primes the system for faster profile updates.
    """

    async def pre_analyze(
        self,
        docs: List[Dict],
        project_description: str,
        llm_manager=None,
    ) -> Dict[str, Any]:
        """Extract topic clusters and keyword candidates from results."""
        if not docs:
            return {"clusters": [], "keyword_candidates": []}

        # Extract all key points and titles
        all_text = []
        for d in docs:
            if d.get("ai_key_points"):
                all_text.extend(d["ai_key_points"])
            elif d.get("title"):
                all_text.append(d["title"])

        # Simple frequency analysis
        from collections import Counter
        word_freq = Counter()
        for text in all_text:
            words = [w.lower().strip() for w in text.split() if len(w) > 3]
            word_freq.update(words)

        # Top keywords not already in project description
        desc_words = set(project_description.lower().split())
        novel_keywords = [
            {"keyword": word, "frequency": count}
            for word, count in word_freq.most_common(30)
            if word not in desc_words and count >= 2
        ]

        # LLM cluster analysis (optional)
        clusters = []
        if llm_manager and len(docs) >= 5:
            try:
                titles = [d.get("title", "")[:60] for d in docs[:15]]
                prompt = (
                    "Group these research paper titles into 2-4 thematic clusters. "
                    "Return a JSON object with a 'clusters' array; each entry has "
                    "'theme' (Chinese name) and 'count' fields. "
                    'Example: {"clusters": [{"theme": "...", "count": 3}]}\n\n'
                    + "\n".join(f"- {t}" for t in titles)
                )
                result = await llm_manager.generate(
                    prompt, temperature=0.2,
                    response_format={"type": "json_object"},
                )
                if result:
                    match = re.search(r'\{[\s\S]*\}', result)
                    if match:
                        data = json.loads(match.group())
                        clusters = data.get("clusters") if isinstance(data, dict) else None
                        if not isinstance(clusters, list):
                            clusters = []
            except Exception as e:
                logger.warning("[ProfilePreAnalyzer] Clustering failed: %s", e)

        return {
            "novel_keywords": novel_keywords[:15],
            "clusters": clusters,
            "total_analyzed": len(docs),
        }


class AutoSkillTrigger:
    """
    Automatically triggers skills based on search results.
    e.g., if a document scores exceptionally high, auto-trigger Deep Dive.
    """

    async def evaluate_triggers(
        self,
        docs: List[Dict],
        round_number: int,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """Check if any auto-skill triggers should fire."""
        triggered = []

        # Auto Deep Dive: if any doc has citation_count > 100, it's a landmark paper
        for doc in docs:
            if doc.get("citation_count", 0) > 100:
                triggered.append({
                    "skill_id": "deep_dive",
                    "reason": f"Landmark paper detected: {doc.get('title', '')[:60]} ({doc.get('citation_count')} citations)",
                    "context": {
                        "project_id": project_id,
                        "document_id": doc.get("_db_id"),  # Set after save
                    },
                })
                break  # Only trigger once per round

        # Auto Trend Spotter: after round 3
        if round_number >= 3:
            triggered.append({
                "skill_id": "trend_spotter",
                "reason": f"Round {round_number} complete, enough data for trend analysis",
                "context": {"project_id": project_id},
                "auto_execute": False,  # Suggest only, don't auto-run
            })

        return triggered
