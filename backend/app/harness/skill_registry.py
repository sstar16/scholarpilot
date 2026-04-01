"""
Skill Registry — manages reusable workflows triggered by user actions.

Adapted from Claude Code's S05 (Knowledge on Demand) pattern.
Skills are lazy-loaded workflows that run only when explicitly invoked.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class SkillTrigger(str, Enum):
    """When a skill can be triggered."""
    USER_ACTION = "user_action"        # User clicks "Run" button
    FEEDBACK_SIGNAL = "feedback_signal" # After feedback with high-relevance mark
    ROUND_COMPLETE = "round_complete"   # After a round completes
    MANUAL = "manual"                   # API call only


@dataclass
class SkillDefinition:
    """Metadata for a registered skill."""
    skill_id: str
    display_name: str
    description: str
    trigger: SkillTrigger
    required_context: List[str] = field(default_factory=list)  # e.g. ["project_id", "round_id"]
    estimated_llm_calls: int = 1
    estimated_duration_seconds: int = 10
    min_round: int = 1  # Minimum round number before skill becomes available

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "display_name": self.display_name,
            "description": self.description,
            "trigger": self.trigger.value,
            "estimated_llm_calls": self.estimated_llm_calls,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "min_round": self.min_round,
        }


# Skill executor type: async function(context) -> result dict
SkillExecutor = Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]


class SkillRegistry:
    """
    Singleton registry of available skills.
    Skills execute as async functions (can be dispatched to Celery if needed).
    """

    _instance: Optional["SkillRegistry"] = None

    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}
        self._executors: Dict[str, SkillExecutor] = {}

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        cls._instance = None

    def register(self, definition: SkillDefinition, executor: SkillExecutor) -> None:
        """Register a skill with its executor."""
        self._skills[definition.skill_id] = definition
        self._executors[definition.skill_id] = executor
        logger.info("[SkillRegistry] Registered: %s", definition.skill_id)

    def list_available(self, current_round: int = 1) -> List[Dict]:
        """List skills available at the current round."""
        return [
            s.to_dict() for s in self._skills.values()
            if current_round >= s.min_round
        ]

    async def execute(self, skill_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a skill by ID with the given context."""
        if skill_id not in self._executors:
            return {"error": f"Skill '{skill_id}' not found"}

        definition = self._skills[skill_id]
        # Validate required context
        missing = [k for k in definition.required_context if k not in context]
        if missing:
            return {"error": f"Missing required context: {missing}"}

        try:
            logger.info("[SkillRegistry] Executing: %s", skill_id)
            result = await self._executors[skill_id](context)
            return {"status": "ok", "skill_id": skill_id, **result}
        except Exception as e:
            logger.error("[SkillRegistry] %s failed: %s", skill_id, e, exc_info=True)
            return {"status": "error", "skill_id": skill_id, "error": str(e)}

    @property
    def skill_count(self) -> int:
        return len(self._skills)
