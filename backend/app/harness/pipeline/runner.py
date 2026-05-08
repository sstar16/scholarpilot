"""
PhaseRunner — topologically ordered phase executor.

Responsibilities:
- Validate the phase DAG at construction (Kahn topo sort + cycle detection).
- For each phase in order:
    1. Check Answer Now interrupt flag (if phase opts in).
    2. Publish SSE round_status (start of progress_range).
    3. Fire PRE_<NAME> hook if mapped to an existing HookPoint.
    4. Run phase.execute(ctx). Catch PhaseSkipped silently.
    5. Fire POST_<NAME> hook if mapped.
    6. Publish SSE round_status (end of progress_range).
- On PhaseAborted: re-raise so caller can return early without marking failed.
- On any other Exception: log and re-raise (caller marks round failed).
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Optional

from app.harness.hook_engine import HookEngine, HookPoint
from app.services.event_bus import EventBus

from .types import Phase, PhaseAborted, PhaseSkipped, RoundContext

logger = logging.getLogger(__name__)


# Map phase.name → (PRE hook, POST hook). Phases without a mapping skip hooks.
# Keeps backwards compatibility with existing HookPoint enum without forcing a
# new value per phase.
_HOOK_MAP: dict[str, tuple[Optional[HookPoint], Optional[HookPoint]]] = {
    "load_round": (HookPoint.ROUND_START, None),
    "fetch": (None, HookPoint.POST_SEARCH),
    "score": (HookPoint.PRE_SCORING, HookPoint.POST_SCORING),
    "dispatch_summaries": (HookPoint.PRE_SUMMARIZE, None),
}


class PhaseRunner:
    def __init__(self, phases: list[Phase]):
        self._phases = self._topo_sort(phases)
        self._hooks = HookEngine.get_instance()

    @staticmethod
    def _topo_sort(phases: list[Phase]) -> list[Phase]:
        if not phases:
            return []
        by_name: dict[str, Phase] = {}
        for p in phases:
            if p.name in by_name:
                raise ValueError(f"duplicate phase name: '{p.name}'")
            by_name[p.name] = p

        indeg: dict[str, int] = {p.name: 0 for p in phases}
        graph: dict[str, list[str]] = defaultdict(list)
        for p in phases:
            for d in p.deps:
                if d not in by_name:
                    raise ValueError(
                        f"phase '{p.name}' depends on unknown phase '{d}'"
                    )
                graph[d].append(p.name)
                indeg[p.name] += 1

        ready: deque[str] = deque(n for n, k in indeg.items() if k == 0)
        order: list[Phase] = []
        while ready:
            n = ready.popleft()
            order.append(by_name[n])
            for m in graph[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if len(order) != len(phases):
            unresolved = [n for n, k in indeg.items() if k > 0]
            raise ValueError(f"cycle detected involving phases: {unresolved}")
        return order

    @property
    def phases(self) -> list[Phase]:
        return list(self._phases)

    async def run(self, ctx: RoundContext) -> RoundContext:
        for p in self._phases:
            if await self._maybe_partial(ctx, p):
                # Partial answer delivered; abort the round.
                raise PhaseAborted(
                    "user_requested_partial",
                    payload={"partial": True, "stage": _partial_stage(p)},
                )

            # 声明式 conditional skip: phase.skip_if(ctx) → True 时整段跳过
            # (比 phase 内部 raise PhaseSkipped 更易写测试 + 不用先进入 hook)
            if await self._should_skip(p, ctx):
                logger.info("[phase] %s skipped via skip_if", p.name)
                ctx.artifacts[p.name] = None
                self._publish_progress(ctx.round_id, p, edge="start")
                self._publish_progress(ctx.round_id, p, edge="end")
                continue

            self._publish_progress(ctx.round_id, p, edge="start")

            pre_hook, post_hook = _HOOK_MAP.get(p.name, (None, None))
            if pre_hook is not None:
                await self._fire(pre_hook, _hook_ctx(ctx, p))

            try:
                output = await p.execute(ctx)
            except PhaseSkipped as e:
                logger.info("[phase] %s skipped: %s", p.name, e)
                ctx.artifacts[p.name] = None
                # Still emit end-progress so UI doesn't get stuck.
                self._publish_progress(ctx.round_id, p, edge="end")
                continue

            ctx.artifacts[p.name] = output

            if post_hook is not None:
                await self._fire(post_hook, _hook_ctx(ctx, p))

            self._publish_progress(ctx.round_id, p, edge="end")
        return ctx

    @staticmethod
    async def _should_skip(phase: Phase, ctx: RoundContext) -> bool:
        """Honor optional `phase.skip_if(ctx) -> bool | Awaitable[bool]`.

        允许同步 / 异步实现; 缺失或抛异常都视作"不跳过", 让 phase 正常执行.
        """
        skip_if = getattr(phase, "skip_if", None)
        if skip_if is None:
            return False
        try:
            result = skip_if(ctx)
            if hasattr(result, "__await__"):
                result = await result
            return bool(result)
        except Exception as e:
            logger.warning(
                "[phase] %s.skip_if() raised %s; running phase as fallback",
                phase.name, e,
            )
            return False

    async def _maybe_partial(self, ctx: RoundContext, phase: Phase) -> bool:
        if not getattr(phase, "can_interrupt", False):
            return False
        from app.services.partial_synthesizer import (
            clear_interrupt_flag,
            is_interrupt_requested,
            synthesize_partial,
        )
        from app.services.answer_now_helpers import deliver_partial_answer

        if not await is_interrupt_requested(ctx.round_id, ctx.redis):
            return False
        try:
            docs_so_far = _collect_docs_so_far(ctx)
            partial = await synthesize_partial(
                round_id=ctx.round_id,
                project_description=(
                    ctx.project.description if ctx.project else ""
                ),
                docs_so_far=docs_so_far,
                current_stage=_partial_stage(phase),
                llm_manager=ctx.llm_manager,
            )
            await deliver_partial_answer(ctx.round_id, partial, ctx.db)
        finally:
            await clear_interrupt_flag(ctx.round_id, ctx.redis)
        return True

    async def _fire(self, hook: HookPoint, payload: dict) -> None:
        try:
            await self._hooks.fire(hook, payload)
        except Exception as e:
            logger.warning("[hook] %s failed: %s", hook.value, e)

    @staticmethod
    def _publish_progress(round_id: str, phase: Phase, edge: str) -> None:
        start, end = phase.progress_range
        progress = start if edge == "start" else end
        EventBus.publish_sync(round_id, "round_status", {
            "status": phase.name,
            "progress": round(progress, 3),
            "message": f"{phase.name} {edge}",
        })


def _partial_stage(phase: Phase) -> str:
    """UI expects legacy stage names ('searching'/'scoring'/'saving'/'summarizing').
    Phase can override via class attr partial_stage; fall back to name."""
    return getattr(phase, "partial_stage", None) or phase.name


def _hook_ctx(ctx: RoundContext, phase: Phase) -> dict:
    """Build a minimal hook payload from RoundContext + phase, mirroring what
    the legacy code passed (round_id, project_id, etc.)."""
    payload: dict = {
        "round_id": ctx.round_id,
        "phase": phase.name,
    }
    if ctx.project is not None:
        payload["project_id"] = str(ctx.project.id)
        if hasattr(ctx.project, "description"):
            payload["project_description"] = (ctx.project.description or "")[:200]
    if ctx.round is not None and hasattr(ctx.round, "round_number"):
        payload["round_number"] = ctx.round.round_number
    return payload


def _collect_docs_so_far(ctx: RoundContext) -> list:
    """Best-effort: prefer score output, then rerank, then fetch."""
    for key in ("score", "rerank", "fetch"):
        if ctx.has(key):
            out = ctx.artifacts[key]
            if isinstance(out, dict):
                docs = out.get("selected_docs") or out.get("docs")
                if docs:
                    return docs
    return []
