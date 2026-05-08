"""Smart Retriever 单元测试 — 不依赖真 LLM/真 DB.

测试三件核心事:
1. reciprocal_rank_fusion 数学正确性 (手算验证)
2. generate_diverse_queries LLM 失败时降级到 [base_query]
3. smart_retrieve enabled=False 时只走单 query
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.smart_retriever import (
    DEFAULT_FINAL_TOP_K,
    RRF_K,
    _coerce_to_query_list,
    _dedupe_preserve_order,
    _safe_json_parse,
    generate_diverse_queries,
    reciprocal_rank_fusion,
    smart_retrieve,
)

# 注意: 不在模块级用 pytestmark = pytest.mark.asyncio,
# 否则同步测试 (RRF / Helpers) 会被警告.
# 异步测试类各自加 class-level marker.


# ─── Fakes ─────────────────────────────────────────────────────

class FakeIndex:
    """模拟 SearchIndex.search() 同步接口."""

    def __init__(self, mapping: dict[str, list[dict]] | None = None,
                 default: list[dict] | None = None):
        self.mapping = mapping or {}
        self.default = default if default is not None else []
        self.calls: list[tuple[str, int, int | None, int | None]] = []

    def search(self, query, limit=200, year_from=None, year_to=None):
        self.calls.append((query, limit, year_from, year_to))
        return self.mapping.get(query, self.default)


class CrashIndex:
    """模拟 SearchIndex.search() 抛异常."""

    def search(self, query, limit=200, year_from=None, year_to=None):
        raise RuntimeError("simulated sqlite failure")


# ─── Test 1: RRF 数学 ──────────────────────────────────────────

class TestReciprocalRankFusion:
    def test_empty_input_returns_empty(self):
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[], []]) == []

    def test_single_ranking_assigns_correct_scores(self):
        """单路输入: 每个 doc 得 1/(60+rank), hits=1."""
        ranking = [
            {"openalex_id": "A"},
            {"openalex_id": "B"},
            {"openalex_id": "C"},
        ]
        fused = reciprocal_rank_fusion([ranking], top_k=10)
        assert [d["openalex_id"] for d in fused] == ["A", "B", "C"]
        assert all(d["rrf_hits"] == 1 for d in fused)
        assert abs(fused[0]["rrf_score"] - 1.0 / 60) < 1e-9
        assert abs(fused[1]["rrf_score"] - 1.0 / 61) < 1e-9
        assert abs(fused[2]["rrf_score"] - 1.0 / 62) < 1e-9

    def test_two_rankings_fuse_correctly(self):
        """手算验证两路融合的精确分数."""
        rankings = [
            # 路 1: A(rank0), B(rank1)
            [{"openalex_id": "A"}, {"openalex_id": "B"}],
            # 路 2: B(rank0), C(rank1)
            [{"openalex_id": "B"}, {"openalex_id": "C"}],
        ]
        # 期望:
        #   A: 1/60         = 0.016667
        #   B: 1/61 + 1/60  = 0.033060   (hits=2, top)
        #   C: 1/61         = 0.016393
        fused = reciprocal_rank_fusion(rankings, top_k=10)
        ids = [d["openalex_id"] for d in fused]
        assert ids == ["B", "A", "C"], f"order should be B>A>C, got {ids}"
        assert fused[0]["rrf_hits"] == 2
        assert fused[1]["rrf_hits"] == 1
        assert fused[2]["rrf_hits"] == 1
        assert abs(fused[0]["rrf_score"] - (1.0 / 61 + 1.0 / 60)) < 1e-9
        assert abs(fused[1]["rrf_score"] - 1.0 / 60) < 1e-9
        assert abs(fused[2]["rrf_score"] - 1.0 / 61) < 1e-9

    def test_top_k_truncation(self):
        rankings = [[{"openalex_id": str(i)} for i in range(20)]]
        fused = reciprocal_rank_fusion(rankings, top_k=5)
        assert len(fused) == 5
        # 必须是分数最高的 5 个 = rank 0..4
        assert [d["openalex_id"] for d in fused] == ["0", "1", "2", "3", "4"]

    def test_payload_preserved_from_first_sighting(self):
        """同一文档被多路命中, 保留首次见到的完整 payload."""
        rankings = [
            [{"openalex_id": "X", "title": "first"}],
            [{"openalex_id": "X", "title": "second", "extra": "field"}],
        ]
        fused = reciprocal_rank_fusion(rankings, top_k=5)
        assert len(fused) == 1
        assert fused[0]["title"] == "first"  # 首次见到
        assert "extra" not in fused[0]
        assert fused[0]["rrf_hits"] == 2

    def test_missing_id_key_skipped(self):
        rankings = [
            [{"openalex_id": "A"}, {"no_id": "skip_me"}, {"openalex_id": "B"}],
        ]
        fused = reciprocal_rank_fusion(rankings, top_k=10)
        ids = [d["openalex_id"] for d in fused]
        assert ids == ["A", "B"]

    def test_non_dict_entries_skipped(self):
        rankings = [
            [{"openalex_id": "A"}, "not a dict", None, {"openalex_id": "B"}],  # type: ignore
        ]
        fused = reciprocal_rank_fusion(rankings, top_k=10)
        assert [d["openalex_id"] for d in fused] == ["A", "B"]

    def test_custom_id_key(self):
        rankings = [
            [{"doc_id": "1"}, {"doc_id": "2"}],
            [{"doc_id": "2"}],
        ]
        fused = reciprocal_rank_fusion(rankings, id_key="doc_id", top_k=10)
        assert fused[0]["doc_id"] == "2"  # 命中两路
        assert fused[0]["rrf_hits"] == 2

    def test_custom_k_constant(self):
        """k 越大, 排序越平滑 (差异越小); 但相对顺序不变."""
        rankings = [[{"openalex_id": "A"}, {"openalex_id": "B"}]]
        fused_k10 = reciprocal_rank_fusion(rankings, k=10, top_k=10)
        fused_k1000 = reciprocal_rank_fusion(rankings, k=1000, top_k=10)
        # 相对顺序一致
        assert [d["openalex_id"] for d in fused_k10] == [d["openalex_id"] for d in fused_k1000]
        # k=10: A=1/10, B=1/11
        assert abs(fused_k10[0]["rrf_score"] - 1.0 / 10) < 1e-9


# ─── Test 2: generate_diverse_queries 失败降级 ────────────────

@pytest.mark.asyncio
class TestGenerateDiverseQueries:
    async def test_llm_exception_falls_back_to_base(self):
        bad_llm = AsyncMock()
        bad_llm.generate.side_effect = RuntimeError("simulated LLM outage")
        result = await generate_diverse_queries("扩散模型", bad_llm, n=5)
        assert result == ["扩散模型"]

    async def test_llm_returns_none_falls_back(self):
        none_llm = AsyncMock()
        none_llm.generate.return_value = None
        result = await generate_diverse_queries("diffusion model", none_llm, n=5)
        assert result == ["diffusion model"]

    async def test_llm_returns_empty_string_falls_back(self):
        empty_llm = AsyncMock()
        empty_llm.generate.return_value = "   "
        result = await generate_diverse_queries("foo", empty_llm, n=5)
        assert result == ["foo"]

    async def test_llm_returns_garbage_falls_back(self):
        garbage_llm = AsyncMock()
        garbage_llm.generate.return_value = "I cannot help with that."
        result = await generate_diverse_queries("foo", garbage_llm, n=5)
        assert result == ["foo"]

    async def test_llm_returns_valid_json_object(self):
        good_llm = AsyncMock()
        good_llm.generate.return_value = '{"queries": ["q1", "q2", "q3"]}'
        result = await generate_diverse_queries("base", good_llm, n=5)
        assert result[0] == "base", "base_query must be first"
        assert "q1" in result and "q2" in result and "q3" in result
        assert len(result) == 4  # base + 3

    async def test_llm_returns_valid_json_array(self):
        """LLM 偷偷返回顶层 array 也要兼容."""
        good_llm = AsyncMock()
        good_llm.generate.return_value = '["q1", "q2"]'
        result = await generate_diverse_queries("base", good_llm, n=5)
        assert result == ["base", "q1", "q2"]

    async def test_llm_returns_fenced_json(self):
        good_llm = AsyncMock()
        good_llm.generate.return_value = '```json\n{"queries":["a","b"]}\n```'
        result = await generate_diverse_queries("base", good_llm, n=5)
        assert "a" in result and "b" in result

    async def test_n_le_1_skips_llm(self):
        llm = AsyncMock()
        result = await generate_diverse_queries("base", llm, n=1)
        assert result == ["base"]
        llm.generate.assert_not_called()

    async def test_none_llm_manager_returns_base(self):
        result = await generate_diverse_queries("base", None, n=5)
        assert result == ["base"]

    async def test_empty_base_query_returns_empty(self):
        result = await generate_diverse_queries("", AsyncMock(), n=5)
        assert result == []
        result = await generate_diverse_queries("   ", AsyncMock(), n=5)
        assert result == []

    async def test_dedupe_case_insensitive(self):
        """LLM 返回和 base_query 大小写不同的重复词应去掉."""
        good_llm = AsyncMock()
        good_llm.generate.return_value = '{"queries": ["BASE", "Base ", "unique"]}'
        result = await generate_diverse_queries("base", good_llm, n=5)
        # base + unique (BASE/Base 都被去重)
        assert result == ["base", "unique"]

    async def test_truncates_to_n(self):
        good_llm = AsyncMock()
        good_llm.generate.return_value = (
            '{"queries":["q1","q2","q3","q4","q5","q6","q7","q8","q9"]}'
        )
        result = await generate_diverse_queries("base", good_llm, n=5)
        assert len(result) == 5

    async def test_temperature_above_cache_threshold(self):
        """关键: temperature 必须 > 0.4 否则会 hit prompt cache."""
        from app.services.smart_retriever import DIVERSE_TEMPERATURE
        assert DIVERSE_TEMPERATURE > 0.4, \
            "DIVERSE_TEMPERATURE must be > 0.4 to bypass enable_llm_cache threshold"

    async def test_uses_high_temperature(self):
        """验证调用时确实把高 temperature 传给 LLM."""
        from app.services.smart_retriever import DIVERSE_TEMPERATURE
        good_llm = AsyncMock()
        good_llm.generate.return_value = '{"queries":["q1"]}'
        await generate_diverse_queries("base", good_llm, n=3)
        call_kwargs = good_llm.generate.call_args.kwargs
        assert call_kwargs["temperature"] == DIVERSE_TEMPERATURE
        assert call_kwargs["temperature"] > 0.4


# ─── Test 3: smart_retrieve enabled=False ──────────────────────

@pytest.mark.asyncio
class TestSmartRetrieveDisabled:
    async def test_enabled_false_uses_single_query(self):
        idx = FakeIndex(default=[
            {"openalex_id": "X", "bm25_score": -10.0, "publication_year": 2024},
            {"openalex_id": "Y", "bm25_score": -8.0, "publication_year": 2023},
        ])
        # LLM 必须被绝对不调用
        unused_llm = AsyncMock()
        unused_llm.generate.side_effect = AssertionError("LLM should not be called")

        env = await smart_retrieve(
            "test", idx, unused_llm,
            enabled=False, final_top_k=10,
        )
        assert env["smart_enabled"] is False
        assert env["fallback_reason"] == "feature_flag_off"
        assert env["queries_used"] == ["test"]
        assert len(env["docs"]) == 2
        assert env["docs"][0]["openalex_id"] == "X"
        # 单路也应该有 rrf 字段 (一致接口)
        assert env["docs"][0]["rrf_hits"] == 1
        assert env["docs"][0]["rrf_score"] > 0
        unused_llm.generate.assert_not_called()
        # search 只调一次, 用原 query
        assert len(idx.calls) == 1
        assert idx.calls[0][0] == "test"

    async def test_no_llm_manager_uses_single_query(self):
        idx = FakeIndex(default=[{"openalex_id": "Z"}])
        env = await smart_retrieve("q", idx, None, enabled=True)
        assert env["smart_enabled"] is False
        assert env["fallback_reason"] == "no_llm_manager"
        assert env["queries_used"] == ["q"]

    async def test_n_queries_le_1_uses_single_query(self):
        idx = FakeIndex(default=[{"openalex_id": "Z"}])
        unused_llm = AsyncMock()
        unused_llm.generate.side_effect = AssertionError("should not be called")
        env = await smart_retrieve("q", idx, unused_llm, enabled=True, n_queries=1)
        assert env["smart_enabled"] is False
        assert env["fallback_reason"] == "n_queries_le_1"
        unused_llm.generate.assert_not_called()


# ─── Test 4: smart_retrieve 端到端 (mock) ──────────────────────

@pytest.mark.asyncio
class TestSmartRetrieveEndToEnd:
    async def test_end_to_end_diverse_path(self):
        good_llm = AsyncMock()
        good_llm.generate.return_value = (
            '{"queries":["english query","alt phrasing","specific term"]}'
        )
        idx = FakeIndex(mapping={
            "扩散模型": [{"openalex_id": "P1"}, {"openalex_id": "P2"}],
            "english query": [{"openalex_id": "P2"}, {"openalex_id": "P3"}],
            "alt phrasing": [{"openalex_id": "P3"}, {"openalex_id": "P4"}],
            "specific term": [{"openalex_id": "P5"}],
        })
        env = await smart_retrieve(
            "扩散模型", idx, good_llm,
            n_queries=5, final_top_k=10,
        )
        assert env["smart_enabled"] is True
        assert env["fallback_reason"] is None
        assert env["queries_used"][0] == "扩散模型"
        assert len(env["queries_used"]) == 4  # base + 3 diverse
        # P2 + P3 各命中 2 路, 应该排前面
        top_ids = {d["openalex_id"] for d in env["docs"][:2]}
        assert top_ids == {"P2", "P3"}
        # diagnostic 字段
        assert env["per_query_counts"]["扩散模型"] == 2
        assert env["per_query_counts"]["specific term"] == 1

    async def test_diverse_returns_only_base_marked_partial_fallback(self):
        """LLM 返回的 query 全部被去重剩下只有 base, 标 partial fallback 但仍跑流程."""
        good_llm = AsyncMock()
        good_llm.generate.return_value = '{"queries":["BASE","Base","base"]}'
        idx = FakeIndex(default=[{"openalex_id": "X"}])
        env = await smart_retrieve("base", idx, good_llm, n_queries=5)
        assert env["queries_used"] == ["base"]
        assert env["smart_enabled"] is False
        assert env["fallback_reason"] == "diverse_returned_only_base"
        assert len(env["docs"]) == 1

    async def test_year_filter_propagates(self):
        idx = FakeIndex(default=[])
        good_llm = AsyncMock()
        good_llm.generate.return_value = '{"queries":["alt"]}'
        await smart_retrieve(
            "base", idx, good_llm, n_queries=2,
            year_from=2020, year_to=2024,
        )
        for q, limit, yf, yt in idx.calls:
            assert yf == 2020
            assert yt == 2024

    async def test_search_crash_per_query_returns_empty_for_that_query(self):
        """单路 search 抛异常应该被吞掉, 不影响其他路."""
        good_llm = AsyncMock()
        good_llm.generate.return_value = '{"queries":["alt"]}'

        class PartialCrashIndex:
            def search(self, q, limit=200, year_from=None, year_to=None):
                if q == "alt":
                    raise RuntimeError("boom")
                return [{"openalex_id": "OK"}]

        env = await smart_retrieve("base", PartialCrashIndex(), good_llm, n_queries=2)
        # base 路成功, alt 路 0 (吞了异常)
        assert env["per_query_counts"]["base"] == 1
        assert env["per_query_counts"]["alt"] == 0
        assert len(env["docs"]) == 1

    async def test_empty_query_returns_empty_envelope(self):
        env = await smart_retrieve("", FakeIndex(), AsyncMock())
        assert env["docs"] == []
        assert env["fallback_reason"] == "empty_query"
        assert env["smart_enabled"] is False

    async def test_envelope_shape_is_stable(self):
        """envelope 字段集合必须稳定 (上层依赖)."""
        env = await smart_retrieve("q", FakeIndex(), None, enabled=False)
        assert set(env.keys()) == {
            "docs", "queries_used", "per_query_counts",
            "smart_enabled", "fallback_reason",
        }


# ─── Test 5: 辅助函数 ──────────────────────────────────────────

class TestHelpers:
    def test_safe_json_parse_direct_object(self):
        assert _safe_json_parse('{"a":1}') == {"a": 1}

    def test_safe_json_parse_direct_array(self):
        assert _safe_json_parse('[1,2,3]') == [1, 2, 3]

    def test_safe_json_parse_fenced(self):
        assert _safe_json_parse('```json\n{"a":1}\n```') == {"a": 1}
        assert _safe_json_parse('```\n[1,2]\n```') == [1, 2]

    def test_safe_json_parse_embedded(self):
        assert _safe_json_parse('preamble {"a":1} trailing') == {"a": 1}

    def test_safe_json_parse_garbage_returns_none(self):
        assert _safe_json_parse("no json here") is None
        assert _safe_json_parse("") is None
        assert _safe_json_parse(None) is None
        assert _safe_json_parse("   ") is None

    def test_coerce_query_list_from_dict(self):
        assert _coerce_to_query_list({"queries": ["a", "b"]}) == ["a", "b"]
        assert _coerce_to_query_list({"results": ["x"]}) == ["x"]

    def test_coerce_query_list_from_array(self):
        assert _coerce_to_query_list(["a", "b"]) == ["a", "b"]

    def test_coerce_query_list_skips_non_strings(self):
        assert _coerce_to_query_list({"queries": ["a", None, {}, "b"]}) == ["a", "b"]

    def test_coerce_query_list_handles_none(self):
        assert _coerce_to_query_list(None) == []

    def test_dedupe_preserves_order(self):
        assert _dedupe_preserve_order(["a", "B", "a", "b", "C"]) == ["a", "B", "C"]

    def test_dedupe_strips_whitespace(self):
        assert _dedupe_preserve_order([" a ", "a", "  "]) == ["a"]
