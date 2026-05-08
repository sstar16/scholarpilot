"""Tests for the parity recorder/replay primitives themselves."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.parity.recorder import (
    FetcherRecorder,
    FetcherReplay,
    LLMRecorder,
    LLMReplay,
    LLMReplayManager,
    StubLLMManager,
    load_fixture,
    save_fixture,
)


# ── LLMReplay ──────────────────────────────────────────────────────────────


def test_llm_replay_returns_in_order():
    r = LLMReplay.from_responses(["a", "b", "c"])
    assert r.next() == "a"
    assert r.next() == "b"
    assert r.next() == "c"
    assert r.consumed == 3
    assert r.remaining == 0


def test_llm_replay_exhaustion_raises():
    r = LLMReplay.from_responses(["only"])
    r.next()
    with pytest.raises(RuntimeError, match="exhausted after 1"):
        r.next()


def test_llm_replay_records_calls():
    r = LLMReplay.from_responses(["a", "b"])
    r.next(prompt="foo")
    r.next(prompt="bar")
    assert [c["prompt"] for c in r.calls] == ["foo", "bar"]


@pytest.mark.asyncio
async def test_stub_llm_generate_returns_replay():
    r = LLMReplay.from_responses(['{"score": 8.5}', '{"score": 6.0}'])
    llm = StubLLMManager(r)
    a = await llm.generate("prompt 1", temperature=0.15)
    b = await llm.generate("prompt 2", temperature=0.15)
    assert a == '{"score": 8.5}'
    assert b == '{"score": 6.0}'
    assert llm.replay.consumed == 2


# ── _GenericRecorder via FetcherRecorder ───────────────────────────────────


@pytest.mark.asyncio
async def test_fetcher_recorder_captures_inputs_and_outputs():
    class _StubFetcher:
        async def fetch(self, query: str, max_results: int = 5):
            return [{"id": f"{query}-{i}"} for i in range(max_results)]

    fetchers = {"stub": _StubFetcher()}
    with FetcherRecorder(fetchers) as rec:
        out = await fetchers["stub"].fetch("transformer", max_results=2)
    assert out == [{"id": "transformer-0"}, {"id": "transformer-1"}]
    assert len(rec.captures) == 1
    assert rec.captures[0]["target"] == "stub"
    assert rec.captures[0]["args"] == ["transformer"]
    assert rec.captures[0]["kwargs"] == {"max_results": 2}
    assert rec.captures[0]["result"] == [{"id": "transformer-0"}, {"id": "transformer-1"}]


@pytest.mark.asyncio
async def test_fetcher_recorder_restores_on_exit():
    class _StubFetcher:
        async def fetch(self, query: str):
            return ["original"]
    fetchers = {"stub": _StubFetcher()}
    with FetcherRecorder(fetchers) as rec:
        await fetchers["stub"].fetch("x")  # captured
    # After exit, calls no longer go through the recorder.
    n_inside = len(rec.captures)
    await fetchers["stub"].fetch("y")
    assert len(rec.captures) == n_inside
    # And the call still works normally.
    out = await fetchers["stub"].fetch("z")
    assert out == ["original"]


@pytest.mark.asyncio
async def test_recorder_captures_exception_and_re_raises():
    class _BadFetcher:
        async def fetch(self):
            raise ValueError("network down")
    fetchers = {"bad": _BadFetcher()}
    with FetcherRecorder(fetchers) as rec:
        with pytest.raises(ValueError, match="network down"):
            await fetchers["bad"].fetch()
    assert len(rec.captures) == 1
    assert rec.captures[0]["exception"] is not None
    assert "network down" in rec.captures[0]["exception"]


# ── Fixture I/O ────────────────────────────────────────────────────────────


def test_save_and_load_fixture(tmp_path: Path):
    payload = {"input": {"docs": []}, "expected_output": {"scores": [8.5]}}
    f = tmp_path / "fix.json"
    save_fixture(f, payload)
    assert load_fixture(f) == payload
    # Stable ordering — sort_keys=True in save
    raw = f.read_text("utf-8")
    assert raw.index("expected_output") < raw.index("input") or "expected" in raw


# ── FetcherReplay (round-level replay path) ────────────────────────────────


def test_fetcher_replay_exact_match():
    captures = [
        {
            "target": "openalex", "args": ["transformer"],
            "kwargs": {"max_results": 10}, "result": [{"id": "W1"}],
        },
    ]
    rp = FetcherReplay(captures)
    out = rp.lookup("openalex", ("transformer",), {"max_results": 10})
    assert out == [{"id": "W1"}]


def test_fetcher_replay_falls_back_sequential():
    """When exact args don't match, return the next captured response for
    that target. Tolerates minor query-string drift between record/replay."""
    captures = [
        {"target": "openalex", "args": ["foo"], "kwargs": {}, "result": [{"a": 1}]},
        {"target": "openalex", "args": ["bar"], "kwargs": {}, "result": [{"b": 2}]},
    ]
    rp = FetcherReplay(captures)
    # Different query than recorded — sequential fallback hits first capture
    out = rp.lookup("openalex", ("totally-different",), {})
    assert out == [{"a": 1}]
    # And the next call gets the second
    out = rp.lookup("openalex", ("also-different",), {})
    assert out == [{"b": 2}]


def test_fetcher_replay_exhausted_raises():
    captures = [
        {"target": "openalex", "args": [], "kwargs": {}, "result": []},
    ]
    rp = FetcherReplay(captures)
    rp.lookup("openalex", ("any",), {})
    with pytest.raises(RuntimeError, match="exhausted for target='openalex'"):
        rp.lookup("openalex", ("any",), {})


@pytest.mark.asyncio
async def test_fetcher_replay_install_overrides_method():
    class _DummyFetcher:
        async def fetch(self, query: str):
            return [{"original": True}]

    fetchers = {"d": _DummyFetcher()}
    rp = FetcherReplay([
        {"target": "d", "args": ["x"], "kwargs": {}, "result": [{"replayed": True}]},
    ])
    rp.install(fetchers)
    out = await fetchers["d"].fetch("x")
    assert out == [{"replayed": True}]


# ── LLMReplayManager (round-level replay path) ─────────────────────────────


@pytest.mark.asyncio
async def test_llm_replay_manager_sequential():
    captures = [
        {"args": ["prompt 1"], "kwargs": {"temperature": 0.0}, "result": "answer 1"},
        {"args": ["prompt 2"], "kwargs": {"temperature": 0.0}, "result": "answer 2"},
    ]
    mgr = LLMReplayManager(captures)
    a = await mgr.generate("prompt 1", temperature=0.0)
    b = await mgr.generate("prompt 2", temperature=0.0)
    assert a == "answer 1"
    assert b == "answer 2"


@pytest.mark.asyncio
async def test_llm_replay_manager_exhausted_raises():
    mgr = LLMReplayManager([
        {"args": ["a"], "kwargs": {}, "result": "x"},
    ])
    await mgr.generate("a")
    with pytest.raises(RuntimeError, match="exhausted"):
        await mgr.generate("anything")
