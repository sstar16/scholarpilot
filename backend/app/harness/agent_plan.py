"""
Agent Search Plan — structured output from the Search Strategy Agent.
Converts to the existing QueryPlan dataclass for downstream compatibility.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class ToolInvocation:
    """A single tool (data source) invocation planned by the agent."""
    tool_id: str
    max_results: int = 20
    priority: int = 1   # 1=must, 2=nice-to-have


@dataclass
class AgentSearchPlan:
    """
    The agent's complete search strategy for one round.
    Created by SearchStrategyAgent.plan_round().
    """
    tools: List[ToolInvocation] = field(default_factory=list)
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    boost_terms: List[str] = field(default_factory=list)
    exclude_terms: List[str] = field(default_factory=list)
    scoring_adjustments: Dict[str, float] = field(default_factory=dict)
    rationale: str = ""

    @property
    def tool_ids(self) -> List[str]:
        return [t.tool_id for t in self.tools]

    @property
    def max_results_per_source(self) -> int:
        if not self.tools:
            return 20
        return max(t.max_results for t in self.tools)

    def to_query_plan(
        self,
        base_query: str,
        original_chinese_query: Optional[str],
        english_query_source: str,
        cn_query_source: str,
        expanded_terms: List[str],
        anchor_keywords: List[str],
        profile_injected_en: List[str],
        profile_injected_zh: List[str],
        profile_query_extension: str,
        language_scope: str,
    ):
        """
        Convert agent plan to the existing QueryPlan dataclass.
        Preserves the existing pipeline's expected interface.
        """
        from app.services.query_builder import QueryPlan

        # Merge agent's boost terms with existing expanded terms
        merged_expanded = list(expanded_terms)
        for term in self.boost_terms:
            if term not in merged_expanded:
                merged_expanded.append(term)

        # Use agent's exclude terms if provided, else use existing
        exclude = self.exclude_terms if self.exclude_terms else []

        return QueryPlan(
            base_query=base_query,
            expanded_terms=merged_expanded,
            exclude_terms=exclude,
            year_from=self.year_from,
            year_to=self.year_to or datetime.now().year,
            sources=self.tool_ids,
            max_results_per_source=self.max_results_per_source,
            language_scope=language_scope,
            original_chinese_query=original_chinese_query,
            english_query_source=english_query_source,
            cn_query_source=cn_query_source,
            profile_injected_en=profile_injected_en,
            profile_injected_zh=profile_injected_zh,
            profile_query_extension=profile_query_extension,
            anchor_keywords=anchor_keywords,
        )

    @classmethod
    def from_json(cls, data: dict) -> "AgentSearchPlan":
        """Parse from LLM JSON output."""
        tools = []
        for t in data.get("tools", []):
            tools.append(ToolInvocation(
                tool_id=t.get("tool_id", ""),
                max_results=t.get("max_results", 20),
                priority=t.get("priority", 1),
            ))

        year_range = data.get("year_range", {})

        return cls(
            tools=tools,
            year_from=year_range.get("from"),
            year_to=year_range.get("to"),
            boost_terms=data.get("boost_terms", []),
            exclude_terms=data.get("exclude_terms", []),
            scoring_adjustments=data.get("scoring_adjustments", {}),
            rationale=data.get("rationale", ""),
        )
