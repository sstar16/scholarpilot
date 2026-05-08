"""Tests for PhaseRunner: topo sort, cycle detection, deps validation,
PhaseSkipped/PhaseAborted handling, hook & progress emission."""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub the Answer-Now helper modules in sys.modules BEFORE importing the runner,
# so its lazy imports pick up these doubles instead of pulling the real
# (asyncpg/sqlalchemy-laden) modules at collection time. The fixture below then
# rewires the attributes per-test.
_partial_stub = types.ModuleType("app.services.partial_synthesizer")
_partial_stub.is_interrupt_requested = AsyncMock(return_value=False)
_partial_stub.synthesize_partial = AsyncMock(return_value={"partial": "answer"})
_partial_stub.clear_interrupt_flag = AsyncMock()
sys.modules.setdefault("app.services.partial_synthesizer", _partial_stub)

_answer_stub = types.ModuleType("app.services.answer_now_helpers")
_answer_stub.deliver_partial_answer = AsyncMock()
sys.modules.setdefault("app.services.answer_now_helpers", _answer_stub)

from app.harness.pipeline import (  # noqa: E402
    Phase,
    PhaseAborted,
    PhaseRunner,
    PhaseSkipped,
    RoundContext,
)


@dataclass
class _StubPhase:
    name: str
    deps: list[str] = field(default_factory=list)
    progress_range: tuple[float, float] = (0.0, 1.0)
    can_interrupt: bool = False
    partial_stage: str | None = None
    raise_skip: bool = False
    raise_abort: bool = False
    raise_error: Exception | None = None
    output: Any = None
    calls: list[str] = field(default_factory=list)

    async def execute(self, ctx: RoundContext):
        self.calls.append(self.name)
        if self.raise_skip:
            raise PhaseSkipped(f"{self.name} skipped intentionally")
        if self.raise_abort:
            raise PhaseAborted("test abort", payload={"from": self.name})
        if self.raise_error is not None:
            raise self.raise_error
        return self.output if self.output is not None else {"phase": self.name}


def _ctx() -> RoundContext:
    return RoundContext(
        round_id="round-test",
        db=MagicMock(),
        redis=MagicMock(),
        llm_manager=MagicMock(),
    )


# ── Construction-time validation ───────────────────────────────────────────


def test_topo_sort_respects_deps():
    a = _StubPhase("a")
    b = _StubPhase("b", deps=["a"])
    c = _StubPhase("c", deps=["b"])
    runner = PhaseRunner([c, a, b])  # intentionally out of order
    assert [p.name for p in runner.phases] == ["a", "b", "c"]


def test_diamond_deps():
    a = _StubPhase("a")
    b = _StubPhase("b", deps=["a"])
    c = _StubPhase("c", deps=["a"])
    d = _StubPhase("d", deps=["b", "c"])
    runner = PhaseRunner([d, c, b, a])
    order = [p.name for p in runner.phases]
    assert order[0] == "a"
    assert order[-1] == "d"
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_cycle_detection():
    a = _StubPhase("a", deps=["b"])
    b = _StubPhase("b", deps=["a"])
    with pytest.raises(ValueError, match="cycle"):
        PhaseRunner([a, b])


def test_missing_dep_rejected():
    a = _StubPhase("a", deps=["nonexistent"])
    with pytest.raises(ValueError, match="unknown phase"):
        PhaseRunner([a])


def test_duplicate_name_rejected():
    a1 = _StubPhase("a")
    a2 = _StubPhase("a")
    with pytest.raises(ValueError, match="duplicate"):
        PhaseRunner([a1, a2])


def test_empty_phase_list():
    runner = PhaseRunner([])
    assert runner.phases == []


# ── Run-time behaviour (with EventBus + HookEngine patched) ────────────────


@pytest.fixture(autouse=True)
def _patch_side_effects():
    with patch("app.harness.pipeline.runner.EventBus") as bus, \
         patch.object(
             __import__("app.harness.pipeline.runner", fromlist=["HookEngine"]).HookEngine,
             "get_instance",
         ) as hook_inst:
        bus.publish_sync = MagicMock()
        engine = MagicMock()
        engine.fire = AsyncMock()
        hook_inst.return_value = engine
        yield bus, engine


@pytest.mark.asyncio
async def test_run_executes_all_phases_in_order(_patch_side_effects):
    a = _StubPhase("a")
    b = _StubPhase("b", deps=["a"])
    c = _StubPhase("c", deps=["b"])
    runner = PhaseRunner([a, b, c])
    ctx = _ctx()
    await runner.run(ctx)
    assert a.calls == ["a"]
    assert b.calls == ["b"]
    assert c.calls == ["c"]
    assert ctx.artifacts == {
        "a": {"phase": "a"},
        "b": {"phase": "b"},
        "c": {"phase": "c"},
    }


@pytest.mark.asyncio
async def test_phase_skipped_does_not_break_chain(_patch_side_effects):
    a = _StubPhase("a", raise_skip=True)
    b = _StubPhase("b", deps=["a"])
    runner = PhaseRunner([a, b])
    ctx = _ctx()
    await runner.run(ctx)
    assert ctx.artifacts["a"] is None
    assert ctx.artifacts["b"] == {"phase": "b"}


@pytest.mark.asyncio
async def test_phase_aborted_propagates(_patch_side_effects):
    a = _StubPhase("a", raise_abort=True)
    b = _StubPhase("b", deps=["a"])
    runner = PhaseRunner([a, b])
    ctx = _ctx()
    with pytest.raises(PhaseAborted) as exc:
        await runner.run(ctx)
    assert exc.value.payload == {"from": "a"}
    assert b.calls == []  # downstream never ran


@pytest.mark.asyncio
async def test_unhandled_exception_propagates(_patch_side_effects):
    boom = RuntimeError("boom")
    a = _StubPhase("a", raise_error=boom)
    runner = PhaseRunner([a])
    ctx = _ctx()
    with pytest.raises(RuntimeError, match="boom"):
        await runner.run(ctx)


@pytest.mark.asyncio
async def test_progress_emitted_at_start_and_end(_patch_side_effects):
    bus, _ = _patch_side_effects
    a = _StubPhase("a", progress_range=(0.10, 0.30))
    runner = PhaseRunner([a])
    await runner.run(_ctx())
    calls = bus.publish_sync.call_args_list
    assert len(calls) == 2
    progresses = [c.args[2]["progress"] for c in calls]
    assert progresses == [0.10, 0.30]


@pytest.mark.asyncio
async def test_known_hook_fires_on_score(_patch_side_effects):
    bus, engine = _patch_side_effects
    a = _StubPhase("score")
    runner = PhaseRunner([a])
    await runner.run(_ctx())
    # score has both PRE_SCORING and POST_SCORING mapped → 2 fire calls
    assert engine.fire.await_count == 2


@pytest.mark.asyncio
async def test_unknown_phase_skips_hooks(_patch_side_effects):
    bus, engine = _patch_side_effects
    a = _StubPhase("totally_unknown_phase")
    runner = PhaseRunner([a])
    await runner.run(_ctx())
    assert engine.fire.await_count == 0


@pytest.fixture
def _interrupt_stubs():
    """Rebind the stub-module mocks per-test so call counts are isolated."""
    sys.modules["app.services.partial_synthesizer"].is_interrupt_requested = (
        AsyncMock(return_value=False)
    )
    sys.modules["app.services.partial_synthesizer"].synthesize_partial = (
        AsyncMock(return_value={"partial": "answer"})
    )
    sys.modules["app.services.partial_synthesizer"].clear_interrupt_flag = (
        AsyncMock()
    )
    sys.modules["app.services.answer_now_helpers"].deliver_partial_answer = (
        AsyncMock()
    )
    return sys.modules["app.services.partial_synthesizer"]


@pytest.mark.asyncio
async def test_can_interrupt_triggers_partial(_patch_side_effects, _interrupt_stubs):
    _interrupt_stubs.is_interrupt_requested = AsyncMock(return_value=True)
    a = _StubPhase("score", can_interrupt=True, partial_stage="scoring")
    runner = PhaseRunner([a])
    ctx = _ctx()
    ctx.project = MagicMock()
    ctx.project.description = "demo"
    ctx.artifacts["fetch"] = {"selected_docs": [{"title": "foo"}]}

    with pytest.raises(PhaseAborted) as exc:
        await runner.run(ctx)
    assert exc.value.payload["stage"] == "scoring"
    assert a.calls == []  # interrupted before execute


@pytest.mark.asyncio
async def test_can_interrupt_no_flag_runs_normally(_patch_side_effects, _interrupt_stubs):
    _interrupt_stubs.is_interrupt_requested = AsyncMock(return_value=False)
    a = _StubPhase("rerank", can_interrupt=True, partial_stage="searching")
    runner = PhaseRunner([a])
    ctx = _ctx()
    await runner.run(ctx)
    assert a.calls == ["rerank"]


def test_ctx_get_unset_phase_raises():
    ctx = _ctx()
    with pytest.raises(KeyError, match="not yet executed|declare it in deps"):
        ctx.get("never_ran")


def test_ctx_has_returns_membership():
    ctx = _ctx()
    ctx.artifacts["foo"] = {"x": 1}
    assert ctx.has("foo") is True
    assert ctx.has("bar") is False


# ── skip_if (declarative conditional skip) ───────────────────────────


@dataclass
class _SkipIfPhase:
    """Phase stub that exposes a skip_if(ctx) callable for runner introspection."""
    name: str
    deps: list[str] = field(default_factory=list)
    progress_range: tuple[float, float] = (0.0, 1.0)
    skip_if_fn: Any = None
    calls: list[str] = field(default_factory=list)

    def skip_if(self, ctx: RoundContext) -> Any:
        if self.skip_if_fn is None:
            return False
        return self.skip_if_fn(ctx)

    async def execute(self, ctx: RoundContext):
        self.calls.append(self.name)
        return {"phase": self.name}


@pytest.mark.asyncio
async def test_skip_if_true_skips_phase(_patch_side_effects):
    p = _SkipIfPhase("score", skip_if_fn=lambda ctx: True)
    runner = PhaseRunner([p])
    ctx = _ctx()
    await runner.run(ctx)
    assert p.calls == []                       # never executed
    assert ctx.artifacts.get("score") is None  # but artifact slot allocated


@pytest.mark.asyncio
async def test_skip_if_false_runs_phase(_patch_side_effects):
    p = _SkipIfPhase("score", skip_if_fn=lambda ctx: False)
    runner = PhaseRunner([p])
    ctx = _ctx()
    await runner.run(ctx)
    assert p.calls == ["score"]
    assert ctx.artifacts["score"] == {"phase": "score"}


@pytest.mark.asyncio
async def test_skip_if_async_respected(_patch_side_effects):
    async def _aif(ctx):
        return True
    p = _SkipIfPhase("score", skip_if_fn=_aif)
    runner = PhaseRunner([p])
    ctx = _ctx()
    await runner.run(ctx)
    assert p.calls == []


@pytest.mark.asyncio
async def test_skip_if_exception_falls_back_to_running(_patch_side_effects):
    """skip_if 抛异常时不应阻塞流水线，phase 仍按正常路径执行 (fail-soft)."""
    def _raises(ctx):
        raise RuntimeError("intentional")
    p = _SkipIfPhase("score", skip_if_fn=_raises)
    runner = PhaseRunner([p])
    ctx = _ctx()
    await runner.run(ctx)
    assert p.calls == ["score"]
    assert ctx.artifacts["score"] == {"phase": "score"}


@pytest.mark.asyncio
async def test_skip_if_uses_ctx_artifacts(_patch_side_effects):
    """常见用法: 上一 phase 的 artifact 决定下一 phase 是否跳过."""
    plan = _SkipIfPhase("plan_query")
    score = _SkipIfPhase(
        "score",
        deps=["plan_query"],
        skip_if_fn=lambda ctx: ctx.has("plan_query") and ctx.get("plan_query").get("phase") == "plan_query",
    )
    runner = PhaseRunner([plan, score])
    ctx = _ctx()
    await runner.run(ctx)
    assert plan.calls == ["plan_query"]
    assert score.calls == []  # skipped because plan_query produced sentinel
