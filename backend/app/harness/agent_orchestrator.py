"""
Search Strategy Agent — the centerpiece of harness engineering.
Replaces hardcoded DEFAULT_ROUND_CONFIGS with dynamic LLM-driven planning.

Adapted from Claude Code's S01 (The Loop) + S03 (Planning) patterns.

Design principles:
1. Feature-flagged: enable_agent_planning defaults to False
2. Deterministic fallback: LLM failure → existing build_query() path
3. Cached: Redis-backed, same inputs → cached output
4. Cheap: Uses DeepSeek (~$0.0001 per call)
"""
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.harness.agent_plan import AgentSearchPlan
from app.harness.prompts.search_strategy import build_strategy_prompt

logger = logging.getLogger(__name__)


class SearchStrategyAgent:
    """
    Plans search strategy for a round using LLM.
    Falls back to deterministic planning on any failure.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url
        self._cache_ttl = 3600  # 1 hour

    async def plan_round(
        self,
        project_description: str,
        round_number: int,
        max_rounds: int,
        profile_positive: List[str],
        profile_negative: List[str],
        tool_reliability: Dict[str, float],
        prev_source_stats: Dict[str, Any],
        llm_manager=None,
    ) -> Optional[AgentSearchPlan]:
        """
        Generate an agent-driven search plan for one round.
        Returns None on failure (caller should use deterministic fallback).
        """
        if llm_manager is None:
            logger.warning("[AgentOrchestrator] No LLM manager, skipping agent planning")
            return None

        # Check cache first
        cache_key = self._build_cache_key(
            project_description, round_number, profile_positive
        )
        cached = await self._check_cache(cache_key)
        if cached:
            logger.info("[AgentOrchestrator] Cache hit for round %d", round_number)
            return cached

        # Build prompt
        prompt = build_strategy_prompt(
            topic=project_description,
            round_number=round_number,
            max_rounds=max_rounds,
            profile_positive=profile_positive,
            profile_negative=profile_negative,
            tool_stats=tool_reliability,
            prev_stats=prev_source_stats,
        )

        # Call LLM
        try:
            result = await llm_manager.generate(prompt, temperature=0.2)
            if not result:
                logger.warning("[AgentOrchestrator] Empty LLM response")
                return None

            # Parse JSON from response
            plan = self._parse_response(result)
            if plan and plan.tools:
                # Validate tool IDs against registry
                plan = self._validate_plan(plan, tool_reliability)
                await self._cache_plan(cache_key, plan)
                logger.info(
                    "[AgentOrchestrator] Round %d plan: %d tools, year %s-%s, rationale: %s",
                    round_number, len(plan.tools), plan.year_from, plan.year_to,
                    plan.rationale[:100],
                )
                return plan

            logger.warning("[AgentOrchestrator] Failed to parse valid plan from LLM")
            return None

        except Exception as e:
            logger.warning("[AgentOrchestrator] LLM call failed, falling back: %s", e)
            return None

    def _parse_response(self, response: str) -> Optional[AgentSearchPlan]:
        """Extract JSON from LLM response and parse into AgentSearchPlan."""
        try:
            # Try to find JSON object in response
            match = re.search(r'\{[\s\S]*\}', response)
            if not match:
                return None
            data = json.loads(match.group())
            return AgentSearchPlan.from_json(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("[AgentOrchestrator] JSON parse error: %s", e)
            return None

    def _validate_plan(
        self, plan: AgentSearchPlan, available_tools: Dict[str, float]
    ) -> AgentSearchPlan:
        """Remove tools that don't exist in the registry."""
        valid_tools = [t for t in plan.tools if t.tool_id in available_tools]
        if not valid_tools:
            # If all agent-selected tools are invalid, keep original
            return plan
        plan.tools = valid_tools
        return plan

    def _build_cache_key(
        self, description: str, round_number: int, profile: List[str]
    ) -> str:
        content = f"{description[:200]}|{round_number}|{','.join(profile[:10])}"
        return f"harness:agent_plan:{hashlib.sha256(content.encode()).hexdigest()[:16]}"

    async def _check_cache(self, key: str) -> Optional[AgentSearchPlan]:
        """Check Redis cache for a previously computed plan."""
        if not self._redis_url:
            return None
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(self._redis_url)
            data = await r.get(key)
            await r.aclose()
            if data:
                return AgentSearchPlan.from_json(json.loads(data))
        except Exception:
            pass
        return None

    async def _cache_plan(self, key: str, plan: AgentSearchPlan) -> None:
        """Cache plan to Redis."""
        if not self._redis_url:
            return
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(self._redis_url)
            data = json.dumps({
                "tools": [{"tool_id": t.tool_id, "max_results": t.max_results, "priority": t.priority} for t in plan.tools],
                "year_range": {"from": plan.year_from, "to": plan.year_to},
                "boost_terms": plan.boost_terms,
                "exclude_terms": plan.exclude_terms,
                "scoring_adjustments": plan.scoring_adjustments,
                "rationale": plan.rationale,
            })
            await r.setex(key, self._cache_ttl, data)
            await r.aclose()
        except Exception:
            pass
