"""
Pipeline types — RoundContext, Phase protocol, control-flow exceptions.

Inspired by GitNexus pipeline-phases/runner.ts: each phase declares deps
explicitly, retrieves prior outputs via ctx.get(name), and either returns a
dict, raises PhaseSkipped (voluntary skip), or raises PhaseAborted (terminate
the round but not as failure — used by Answer Now).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class RoundContext:
    """Mutable context passed to every phase. First-class fields are loaded by
    LoadRoundPhase; phase-specific outputs live in `artifacts`."""
    round_id: str
    db: Any                       # AsyncSession (loose-typed to dodge ORM imports)
    redis: Any                    # redis.asyncio.Redis
    llm_manager: Any              # LLMManager
    round: Any = None             # SearchRound ORM
    project: Any = None           # Project ORM
    session_id: Optional[str] = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    def get(self, phase_name: str) -> Any:
        if phase_name not in self.artifacts:
            raise KeyError(
                f"phase '{phase_name}' has not produced output yet — "
                f"declare it in deps or check execution order"
            )
        return self.artifacts[phase_name]

    def has(self, phase_name: str) -> bool:
        return phase_name in self.artifacts


class PhaseSkipped(Exception):
    """Phase voluntarily skipped (feature flag off, no work to do, ...)."""


@dataclass
class PhaseAborted(Exception):
    """Terminate the round without marking it failed.

    Used by Answer Now: synthesize_partial has already delivered the partial
    answer; runner just needs to stop and let the caller return cleanly.
    """
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Phase(Protocol):
    """A pipeline phase. Each phase is a single concern with explicit deps.

    Required:
        name: unique identifier, used for ctx.get() lookups & hook naming
        deps: names of phases whose outputs this phase reads via ctx.get()
        progress_range: (start, end) ∈ [0, 1] for SSE round_status broadcast
        execute(ctx): async, returns dict (stored in ctx.artifacts[name])

    Optional (default class-level attrs):
        can_interrupt: True ⇒ runner checks Answer Now flag before execute()
        partial_stage: stage name reported to UI on partial synthesis
                       (defaults to phase.name when can_interrupt=True)
        skip_if(ctx): runner 在 execute() 前调用; 返回 True 直接跳过此 phase,
                      不抛异常更声明式. 用于"上一阶段已经做完此 phase 的工作"
                      或"feature flag 关闭"等条件性裁剪. 与 `raise PhaseSkipped`
                      等价但更易写测试.
    """
    name: str
    deps: list[str]
    progress_range: tuple[float, float]

    async def execute(self, ctx: RoundContext) -> Any: ...
