"""
Autonomous Round Controller — the Agent decides when to stop searching.

Replaces the fixed "5 rounds" model with dynamic termination based on:
1. Result saturation (diminishing returns across rounds)
2. User satisfaction signal (feedback quality)
3. Coverage completeness (how many sources have been exhausted)
4. Budget awareness (LLM cost tracking)

The controller runs AFTER each round's feedback is processed.
It returns either:
  - ContinueSearch(reason, adjusted_strategy) → create next round
  - StopSearch(reason, summary) → activate monitoring
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RoundDecision:
    """The agent's decision about whether to continue searching."""
    should_continue: bool
    reason: str
    confidence: float = 0.8  # 0.0 - 1.0
    strategy_adjustments: Optional[Dict[str, Any]] = None  # Hints for next round


DECISION_PROMPT = """You are a research search orchestrator deciding whether to continue or stop searching.

CONTEXT:
- Research topic: {topic}
- Completed rounds: {completed_rounds} of max {max_rounds}
- Results so far: {total_docs_found} documents total
- Latest round: {latest_round_docs} docs found, {latest_high_score} highly rated by user
- User satisfaction rate: {satisfaction_rate}% (docs rated relevant / total rated)
- Sources exhausted: {sources_exhausted}
- Diminishing returns: {diminishing} (latest round found {new_unique_pct}% new unique docs)

DECISION RULES:
- STOP if satisfaction >= 80% AND completed_rounds >= 3
- STOP if diminishing returns (<20% new docs in latest round) AND completed_rounds >= 2
- STOP if all main sources exhausted
- CONTINUE if satisfaction < 50% AND completed_rounds < max
- CONTINUE if user gave strong negative feedback (wants different direction)

OUTPUT (JSON only):
{{
  "should_continue": true/false,
  "reason": "Brief Chinese explanation",
  "confidence": 0.0-1.0,
  "strategy_adjustments": {{
    "broaden_query": true/false,
    "add_sources": ["source_id"],
    "focus_shift": "description of what to focus on next"
  }}
}}"""


class AutonomousRoundController:
    """Decides whether to continue searching after each round."""

    async def decide(
        self,
        project_description: str,
        completed_rounds: int,
        max_rounds: int,
        round_history: List[Dict[str, Any]],
        feedback_summary: Dict[str, Any],
        llm_manager=None,
    ) -> RoundDecision:
        """
        Analyze round history + feedback to decide next action.
        Falls back to simple heuristics if LLM unavailable.
        """
        # Compute metrics
        metrics = self._compute_metrics(round_history, feedback_summary)

        # Try LLM decision
        if llm_manager:
            try:
                decision = await self._llm_decide(
                    project_description, completed_rounds, max_rounds, metrics, llm_manager
                )
                if decision:
                    return decision
            except Exception as e:
                logger.warning("[RoundController] LLM decision failed: %s", e)

        # Fallback: heuristic decision
        return self._heuristic_decide(completed_rounds, max_rounds, metrics)

    def _compute_metrics(
        self, round_history: List[Dict], feedback_summary: Dict
    ) -> Dict[str, Any]:
        """Compute decision-relevant metrics from round history."""
        total_docs = sum(r.get("doc_count", 0) for r in round_history)
        latest = round_history[-1] if round_history else {}

        # Satisfaction rate from feedback
        total_rated = feedback_summary.get("total_rated", 0)
        positive_rated = feedback_summary.get("positive_rated", 0)
        satisfaction = (positive_rated / total_rated * 100) if total_rated > 0 else 0

        # Diminishing returns: % of new unique docs in latest round
        latest_docs = latest.get("doc_count", 0)
        latest_new = latest.get("new_unique_count", latest_docs)
        new_unique_pct = (latest_new / latest_docs * 100) if latest_docs > 0 else 100

        # Latest round high-score docs
        latest_high = latest.get("high_score_count", 0)

        return {
            "total_docs_found": total_docs,
            "latest_round_docs": latest_docs,
            "latest_high_score": latest_high,
            "satisfaction_rate": round(satisfaction, 1),
            "new_unique_pct": round(new_unique_pct, 1),
            "sources_exhausted": latest.get("sources_exhausted", "unknown"),
            "diminishing": new_unique_pct < 30,
        }

    async def _llm_decide(
        self,
        topic: str,
        completed: int,
        max_rounds: int,
        metrics: Dict,
        llm_manager,
    ) -> Optional[RoundDecision]:
        """Use LLM to make the decision."""
        prompt = DECISION_PROMPT.format(
            topic=topic[:200],
            completed_rounds=completed,
            max_rounds=max_rounds,
            **metrics,
        )

        result = await llm_manager.generate(prompt, temperature=0.1)
        if not result:
            return None

        match = re.search(r'\{[\s\S]*\}', result)
        if not match:
            return None

        try:
            data = json.loads(match.group())
            return RoundDecision(
                should_continue=data.get("should_continue", True),
                reason=data.get("reason", ""),
                confidence=data.get("confidence", 0.5),
                strategy_adjustments=data.get("strategy_adjustments"),
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def _heuristic_decide(
        self, completed: int, max_rounds: int, metrics: Dict
    ) -> RoundDecision:
        """Simple rule-based fallback."""
        if completed >= max_rounds:
            return RoundDecision(
                should_continue=False,
                reason=f"已达到最大轮次上限 ({max_rounds})",
                confidence=1.0,
            )

        if completed >= 3 and metrics["satisfaction_rate"] >= 80:
            return RoundDecision(
                should_continue=False,
                reason=f"满意度已达 {metrics['satisfaction_rate']}%，搜索质量足够",
                confidence=0.9,
            )

        if completed >= 2 and metrics["diminishing"]:
            return RoundDecision(
                should_continue=False,
                reason=f"收益递减（最新一轮仅 {metrics['new_unique_pct']}% 新文献）",
                confidence=0.7,
            )

        return RoundDecision(
            should_continue=True,
            reason=f"已完成 {completed} 轮，满意度 {metrics['satisfaction_rate']}%，继续搜索",
            confidence=0.8,
        )
