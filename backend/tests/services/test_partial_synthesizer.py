"""Smoke tests for Answer Now partial synthesizer + redis flag helpers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.services.partial_synthesizer import (
    INTERRUPT_KEY_PREFIX,
    _build_partial_prompt,
    _extract_cited_doc_ids,
    clear_interrupt_flag,
    is_interrupt_requested,
    set_interrupt_flag,
    synthesize_partial,
)

# 注意: async 测试单独 @pytest.mark.asyncio, 同步测试不打 mark
# (pytestmark 全局打 asyncio 会导致同步函数也被警告)


# ---------------------------------------------------------------------------
# Fake Redis (in-memory) — covers happy path + raise path
# ---------------------------------------------------------------------------

class _FakeRedis:
    def __init__(self, raise_on: set[str] | None = None):
        self.store: dict[str, str] = {}
        self.raise_on = raise_on or set()

    async def get(self, key):
        if "get" in self.raise_on:
            raise RuntimeError("boom")
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        if "set" in self.raise_on:
            raise RuntimeError("boom")
        self.store[key] = value

    async def delete(self, key):
        if "delete" in self.raise_on:
            raise RuntimeError("boom")
        self.store.pop(key, None)


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_set_get_clear_roundtrip():
    r = _FakeRedis()
    rid = "abc-123"

    assert await is_interrupt_requested(rid, r) is False
    assert await set_interrupt_flag(rid, r) is True
    # 用底层 store 校验 key 命名
    assert f"{INTERRUPT_KEY_PREFIX}{rid}" in r.store

    assert await is_interrupt_requested(rid, r) is True

    await clear_interrupt_flag(rid, r)
    assert await is_interrupt_requested(rid, r) is False


@pytest.mark.asyncio
async def test_flag_redis_set_failure_returns_false():
    r = _FakeRedis(raise_on={"set"})
    assert await set_interrupt_flag("x", r) is False


@pytest.mark.asyncio
async def test_flag_redis_get_failure_returns_false_not_raise():
    r = _FakeRedis(raise_on={"get"})
    # is_interrupt_requested 必须吞掉异常 (worker 不能因 redis 挂掉崩)
    assert await is_interrupt_requested("x", r) is False


@pytest.mark.asyncio
async def test_flag_clear_failure_silenced():
    r = _FakeRedis(raise_on={"delete"})
    # 不应抛
    await clear_interrupt_flag("x", r)


@pytest.mark.asyncio
async def test_flag_empty_round_id_returns_false():
    r = _FakeRedis()
    assert await is_interrupt_requested("", r) is False
    assert await set_interrupt_flag("", r) is False


# ---------------------------------------------------------------------------
# _build_partial_prompt: prompt 包含必要关键词
# ---------------------------------------------------------------------------

def test_build_partial_prompt_contains_required_keywords():
    docs = [
        {"external_id": "e1", "source": "openalex", "title": "Title 1", "abstract": "A1"},
        {"external_id": "e2", "source": "arxiv", "title": "Title 2", "abstract": "A2"},
    ]
    prompt = _build_partial_prompt(
        project_description="量子计算与药物筛选",
        docs=docs,
        current_stage="scoring",
    )
    # 必须告诉 LLM 这是 Answer Now / partial / 当前 stage
    assert "Answer Now" in prompt
    assert "partial" in prompt or "部分结果" in prompt
    assert "scoring" in prompt
    # 必须把 doc external_id 写进 prompt
    assert "[doc:e1]" in prompt
    assert "[doc:e2]" in prompt
    # 必须包含用户研究方向
    assert "量子计算与药物筛选" in prompt


def test_build_partial_prompt_truncates_long_abstract():
    long_abs = "x" * 2000
    docs = [{"external_id": "e", "title": "t", "abstract": long_abs, "source": "s"}]
    prompt = _build_partial_prompt("desc", docs, "searching")
    # 600 截断 + "..." 结尾
    assert "x" * 600 in prompt
    assert "x" * 1000 not in prompt
    assert "..." in prompt


# ---------------------------------------------------------------------------
# _extract_cited_doc_ids
# ---------------------------------------------------------------------------

def test_extract_cited_doc_ids_only_known_ids():
    docs = [{"external_id": "real-1"}, {"doi": "10.1/real-2"}]
    answer = (
        "Some claim [doc:real-1] and another [doc:10.1/real-2]. "
        "But [doc:fake-99] should be ignored."
    )
    cited = _extract_cited_doc_ids(answer, docs)
    assert "real-1" in cited
    assert "10.1/real-2" in cited
    assert "fake-99" not in cited


def test_extract_cited_doc_ids_dedupes():
    docs = [{"external_id": "a"}]
    answer = "[doc:a] then again [doc:a]."
    assert _extract_cited_doc_ids(answer, docs) == ["a"]


def test_extract_cited_doc_ids_empty_answer():
    assert _extract_cited_doc_ids("", [{"external_id": "x"}]) == []


# ---------------------------------------------------------------------------
# synthesize_partial: edge cases + LLM mocking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_partial_zero_docs_returns_disclaimer_no_llm_call():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=AssertionError("不应调 LLM"))

    result = await synthesize_partial(
        round_id="r",
        project_description="desc",
        docs_so_far=[],
        current_stage="searching",
        llm_manager=llm,
    )
    assert result["partial"] is True
    assert result["confidence"] == 0.0
    assert result["doc_count_used"] == 0
    assert result["interrupted_at_stage"] == "searching"
    assert result["error"] is None
    assert result["doc_ids_cited"] == []
    assert result["disclaimer"]  # 非空
    # 关键: docs=[] 时 LLM mock 的 side_effect 不应触发
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_synthesize_partial_happy_path_calls_llm():
    docs = [
        {"external_id": "e1", "source": "openalex",
         "title": "T1", "abstract": "abs1"},
        {"external_id": "e2", "source": "arxiv",
         "title": "T2", "abstract": "abs2"},
    ]
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value="## Partial\n关键发现 [doc:e1] 还有 [doc:e2].\n"
    )

    result = await synthesize_partial(
        round_id="round-x",
        project_description="主题",
        docs_so_far=docs,
        current_stage="scoring",
        llm_manager=llm,
    )
    llm.generate.assert_awaited_once()
    assert result["partial"] is True
    assert result["doc_count_used"] == 2
    assert result["interrupted_at_stage"] == "scoring"
    assert result["error"] is None
    assert "e1" in result["doc_ids_cited"]
    assert "e2" in result["doc_ids_cited"]
    assert "Partial" in result["answer_markdown"]
    # confidence 启发: 2 docs / 10 = 0.2
    assert 0.1 <= result["confidence"] <= 0.9


@pytest.mark.asyncio
async def test_synthesize_partial_llm_exception_returns_error_payload():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("provider 502"))

    result = await synthesize_partial(
        round_id="r",
        project_description="desc",
        docs_so_far=[{"external_id": "e", "title": "t", "abstract": "a"}],
        current_stage="summarizing",
        llm_manager=llm,
    )
    # 必须不抛, 而是返回结构化 error
    assert result["partial"] is True
    assert result["error"] is not None
    assert "provider 502" in result["error"]
    assert result["confidence"] == 0.0
    assert result["interrupted_at_stage"] == "summarizing"
    assert result["doc_count_used"] == 1


@pytest.mark.asyncio
async def test_synthesize_partial_empty_llm_response_returns_error_payload():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="   ")

    result = await synthesize_partial(
        round_id="r",
        project_description="desc",
        docs_so_far=[{"external_id": "e", "title": "t", "abstract": "a"}],
        current_stage="searching",
        llm_manager=llm,
    )
    assert result["error"] is not None
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_synthesize_partial_max_docs_truncates_input():
    # 50 docs, max_docs=5 -> 应该只用 5 篇
    docs = [
        {"external_id": f"e{i}", "title": f"t{i}", "abstract": "a", "source": "s"}
        for i in range(50)
    ]
    captured: dict = {}

    async def _capture(prompt, **kw):
        captured["prompt"] = prompt
        return "ok [doc:e0]"

    llm = AsyncMock()
    llm.generate = _capture

    result = await synthesize_partial(
        round_id="r",
        project_description="d",
        docs_so_far=docs,
        current_stage="searching",
        llm_manager=llm,
        max_docs=5,
    )
    assert result["doc_count_used"] == 5
    # prompt 中只应有 e0..e4
    assert "[doc:e0]" in captured["prompt"]
    assert "[doc:e4]" in captured["prompt"]
    assert "[doc:e5]" not in captured["prompt"]
