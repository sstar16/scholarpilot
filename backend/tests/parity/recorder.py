"""Recorder/replay primitives for parity testing.

Phase-level usage::

    replay = LLMReplay.from_responses([
        {"answer": "8.5"}, {"answer": "6.0"},
    ])
    llm = StubLLMManager(replay)
    out = await ScorePhase().execute(ctx_with_llm(llm))

Full-round recording (run against real env, then dump JSON)::

    with FetcherRecorder() as fr, LLMRecorder() as lr:
        await execute_round(...)
    save_fixture(fixture_path, fetcher=fr.captures, llm=lr.captures)

Replay tests then load the JSON and assert output ↔ ``expected_output``
matches byte-for-byte (or with ε for floats).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

logger = logging.getLogger(__name__)


# ── LLM replay ──────────────────────────────────────────────────────────────


@dataclass
class LLMReplay:
    """Returns the next response in the configured sequence each call.

    Sequence is consumed strictly in order; raises if exhausted (signals a
    drift between the test fixture and the code under test)."""
    responses: list[Any]
    _idx: int = 0
    calls: list[dict] = field(default_factory=list)

    @classmethod
    def from_responses(cls, responses: list[Any]) -> "LLMReplay":
        return cls(responses=list(responses))

    def next(self, **call_meta: Any) -> Any:
        if self._idx >= len(self.responses):
            raise RuntimeError(
                f"LLMReplay exhausted after {self._idx} calls; "
                f"fixture provides {len(self.responses)} responses but the "
                f"code under test is asking for more."
            )
        resp = self.responses[self._idx]
        self.calls.append({"idx": self._idx, **call_meta})
        self._idx += 1
        return resp

    @property
    def consumed(self) -> int:
        return self._idx

    @property
    def remaining(self) -> int:
        return len(self.responses) - self._idx


class StubLLMManager:
    """Drop-in replacement for the real LLMManager. Implements ``generate``
    to return canned responses from an LLMReplay."""

    def __init__(self, replay: LLMReplay):
        self._replay = replay

    async def generate(self, *args, **kwargs) -> Any:
        # Most callers pass either positional ``messages`` or ``prompt``.
        return self._replay.next(args=args, kwargs={
            k: (v if isinstance(v, (str, int, float, bool)) else type(v).__name__)
            for k, v in kwargs.items()
        })

    async def complete(self, *args, **kwargs) -> Any:
        return self._replay.next(method="complete", args=args)

    @property
    def replay(self) -> LLMReplay:
        return self._replay


# ── Recorders (used during fixture creation; not in CI) ────────────────────


@dataclass
class _CallCapture:
    target: str
    args: tuple
    kwargs: dict
    result: Any
    exception: str | None = None


class _GenericRecorder:
    """Wrap an attribute on each instance with a capturing version. Replaces
    the original on ``__exit__``. Captures keep the call args & result so the
    fixture file is self-contained for replay."""

    def __init__(self, instances: Mapping[str, Any], attr: str):
        # Mapping[SourceId, ...] (the strict Literal-keyed dict from
        # international.py) is fine because Literal is a subtype of str —
        # taking the wider Mapping type avoids dict-invariance friction.
        self._instances: Mapping[str, Any] = instances
        self._attr = attr
        self._originals: dict[str, Callable[..., Awaitable[Any]]] = {}
        self.captures: list[dict] = []

    def __enter__(self):
        for label, inst in self._instances.items():
            self._originals[label] = getattr(inst, self._attr)
            self._wrap(label, inst)
        return self

    def __exit__(self, *_):
        for label, original in self._originals.items():
            setattr(self._instances[label], self._attr, original)

    def _wrap(self, label: str, inst: Any) -> None:
        original = self._originals[label]

        async def wrapped(*args, **kwargs):
            try:
                result = await original(*args, **kwargs)
                self.captures.append({
                    "target": label, "args": list(args), "kwargs": dict(kwargs),
                    "result": _serialise(result),
                })
                return result
            except Exception as e:
                self.captures.append({
                    "target": label, "args": list(args), "kwargs": dict(kwargs),
                    "result": None, "exception": repr(e),
                })
                raise
        setattr(inst, self._attr, wrapped)


def FetcherRecorder(fetchers: Mapping[str, Any]):  # noqa: N802 — factory style
    """Wrap each fetcher's ``fetch`` method to capture (input → response).

    ``fetchers`` is whatever dict ALL_FETCHERS exposes (or a subset for tests)."""
    return _GenericRecorder(fetchers, "fetch")


def LLMRecorder(managers: Mapping[str, Any]):  # noqa: N802
    """Wrap each LLM manager instance's ``generate`` method."""
    return _GenericRecorder(managers, "generate")


# ── Replay-side counterparts ───────────────────────────────────────────────


class FetcherReplay:
    """Replays captured fetcher responses keyed by (target, args, kwargs).

    Order-insensitive: the replay matches by content, so concurrent fetches
    via ``asyncio.gather`` don't trip over each other. Falls back to
    "by-target sequential" if exact match is not found (handles minor query
    string variations between record and replay)."""

    def __init__(self, captures: list[dict]):
        self._by_target_seq: dict[str, list[dict]] = {}
        for c in captures:
            self._by_target_seq.setdefault(c["target"], []).append(c)
        self._consumed: dict[str, int] = {t: 0 for t in self._by_target_seq}

    def lookup(self, target: str, args, kwargs):
        seq = self._by_target_seq.get(target, [])
        # Try exact match first
        for c in seq:
            if list(args) == c["args"] and dict(kwargs) == c["kwargs"]:
                return c["result"]
        # Fall back to next-in-sequence for this target
        idx = self._consumed[target]
        if idx >= len(seq):
            raise RuntimeError(
                f"FetcherReplay exhausted for target={target!r}; "
                f"recorded {len(seq)} calls, replay needs more."
            )
        self._consumed[target] = idx + 1
        return seq[idx]["result"]

    def install(self, fetchers: dict[str, Any]) -> None:
        """Replace each fetcher's ``fetch`` method with a replay function."""
        for label, inst in fetchers.items():
            replay = self

            async def fake_fetch(*args, _label=label, **kwargs):
                return replay.lookup(_label, args, kwargs)
            setattr(inst, "fetch", fake_fetch)


class LLMReplayManager:
    """Drop-in LLM manager whose ``generate`` returns recorded responses.

    Each captured response is consumed at most once. Resolution order:
      1. exact (args, kwargs) match against an unconsumed capture
      2. fallback: next unconsumed capture (lets minor prompt drift through)
      3. all consumed → RuntimeError
    """

    def __init__(self, captures: list[dict]):
        self._seq = list(captures)
        self._consumed = [False] * len(self._seq)

    async def generate(self, *args, **kwargs):
        # 1) exact match against an unconsumed capture
        for i, c in enumerate(self._seq):
            if self._consumed[i]:
                continue
            if list(args) == c["args"] and dict(kwargs) == c["kwargs"]:
                self._consumed[i] = True
                return c["result"]
        # 2) sequential fallback: next unconsumed
        for i, used in enumerate(self._consumed):
            if not used:
                self._consumed[i] = True
                return self._seq[i]["result"]
        # 3) all consumed
        raise RuntimeError(
            "LLMReplayManager exhausted; recorded "
            f"{len(self._seq)} calls, replay needs more."
        )


# ── Fixture I/O ─────────────────────────────────────────────────────────────


def save_fixture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialise(value: Any) -> Any:
    """Best-effort JSON-serialise a captured result (handles common cases)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialise(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):  # pydantic v2
        return value.model_dump()
    return repr(value)
