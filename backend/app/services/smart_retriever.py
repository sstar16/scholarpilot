"""Smart Retrieve: 多路 diverse query + 并行 BM25 + RRF 融合

原理:
1. 用户单 query → LLM 生成 N 个 diverse query (中英互译/技术细节/上位词/同义/口语化)
2. 每个 query 并行调 SearchIndex.search() (asyncio.to_thread 包同步 sqlite)
3. RRF (Reciprocal Rank Fusion) 融合多路结果
4. 返回 top-K 文档 (含 rrf_score / rrf_hits)，给上层 LLM rerank 使用

设计要点:
- 失败永远降级到单 query (LLM 不可用 / JSON 异常 / 都不阻断主流程)
- temperature=0.7 避开 enable_llm_cache 的 ≤0.4 阈值，保证每轮 diverse 不一样
- SearchIndex.search() 已内置 jieba 分词，本模块不再重复处理
- 返回 envelope 而非裸 list, 便于上层诊断 / 灰度切换 / 监控
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ─── 默认参数 ─────────────────────────────────────────────────
DEFAULT_DIVERSE_COUNT = 5
DEFAULT_PER_QUERY_LIMIT = 60
DEFAULT_FINAL_TOP_K = 100
RRF_K = 60  # 标准 RRF 常数 (Cormack et al. 2009)

# diverse query 生成温度: 必须 > 0.4 避开 enable_llm_cache 阈值,
# 否则同一 base_query 永远 hit cache, 失去 diverse 意义
DIVERSE_TEMPERATURE = 0.7


# ─── JSON 解析容错 ─────────────────────────────────────────────

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_FIRST_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_FIRST_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def _safe_json_parse(text: str | None) -> Any:
    """容错 JSON 解析: 剥 ```json 围栏, 兼容顶层 array/object, 失败返回 None.

    支持:
    - 直接 JSON 文本
    - ```json ... ``` 围栏
    - 文本前后有杂乱说明文字 (回退到正则抓取首个 {} 或 [])
    """
    if not text:
        return None
    text = text.strip()
    if not text:
        return None

    # 先尝试直接 parse
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # 剥 ```json``` 围栏
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        inner = fence_match.group(1).strip()
        try:
            return json.loads(inner)
        except (ValueError, TypeError):
            pass

    # 抓首个 object
    obj_match = _FIRST_OBJECT_RE.search(text)
    if obj_match:
        try:
            return json.loads(obj_match.group())
        except (ValueError, TypeError):
            pass

    # 抓首个 array
    arr_match = _FIRST_ARRAY_RE.search(text)
    if arr_match:
        try:
            return json.loads(arr_match.group())
        except (ValueError, TypeError):
            pass

    return None


def _coerce_to_query_list(parsed: Any) -> list[str]:
    """从任意 JSON 结构里抽 query list. 兼容多种 LLM 返回风格."""
    if parsed is None:
        return []
    # 顶层就是 list
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if isinstance(x, (str, int, float)) and str(x).strip()]
    # 顶层是 dict, 找常见 key
    if isinstance(parsed, dict):
        for key in ("queries", "query_list", "results", "data", "items"):
            v = parsed.get(key)
            if isinstance(v, list):
                return [str(x).strip() for x in v if isinstance(x, (str, int, float)) and str(x).strip()]
        # 退而求其次: 取所有 string value
        out = []
        for v in parsed.values():
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
        return out
    return []


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """case-insensitive + strip 去重, 保留首次出现顺序."""
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        s2 = (s or "").strip()
        if not s2:
            continue
        key = s2.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s2)
    return out


# ─── Diverse Query 生成 ───────────────────────────────────────

_DIVERSE_PROMPT_TEMPLATE = """You are a search query diversification assistant for an academic literature retrieval system.

Given the user's base query, generate {n_minus_1} ADDITIONAL diverse search queries that cover DIFFERENT angles of the same intent. The original query will be searched separately, so DO NOT repeat it.

Coverage dimensions (try to spread across these):
1. Chinese ↔ English translation / synonym rewrite
2. More specific technical detail (method name, tool name, dataset name)
3. Broader/upper-level concept
4. Related sub-direction or adjacent topic
5. Colloquial / common-typo / alternative phrasing a user might use

Constraints:
- Each query 2-8 words, BM25-friendly (no boolean operators, no quotes)
- If base query is Chinese, include at least 1 English translation; if English, include at least 1 Chinese version
- No duplicates among themselves
- Avoid generic terms like "paper", "research", "study"
{domain_hint_section}
Base query: {base_query}

Return JSON only, no explanation:
{{"queries": ["query 1", "query 2", ...]}}
"""


async def generate_diverse_queries(
    base_query: str,
    llm_manager,
    *,
    n: int = DEFAULT_DIVERSE_COUNT,
    domain_hint: str | None = None,
) -> list[str]:
    """用 LLM 把单 query 拆成 N 个不同切入角度的查询.

    返回包含原 query 的列表 (原 query 永远第一位).
    LLM 失败 / JSON 解析失败 / 返回空 → 降级到 [base_query].

    n: 总 query 数 (含原 query). 实际让 LLM 生成 n-1 个, 加原 query 凑齐 n.
    domain_hint: 项目 domain (如 "computer_science"), 用来约束生成方向.
    """
    base_query = (base_query or "").strip()
    if not base_query:
        return []
    if n <= 1 or llm_manager is None:
        return [base_query]

    # LLM 只生成额外的 n-1 个, 第一位永远是 base_query
    n_extra = max(1, n - 1)

    domain_section = ""
    if domain_hint:
        domain_section = f"\nDomain context: {domain_hint} (prioritize terminology in this field)\n"

    prompt = _DIVERSE_PROMPT_TEMPLATE.format(
        n_minus_1=n_extra,
        base_query=base_query,
        domain_hint_section=domain_section,
    )

    try:
        raw = await llm_manager.generate(
            prompt,
            temperature=DIVERSE_TEMPERATURE,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.warning("[smart_retrieve] diverse LLM call failed: %s", e)
        return [base_query]

    if not raw:
        logger.info("[smart_retrieve] diverse LLM returned empty, fallback to single query")
        return [base_query]

    parsed = _safe_json_parse(raw)
    candidates = _coerce_to_query_list(parsed)

    if not candidates:
        logger.info(
            "[smart_retrieve] diverse JSON parse yielded nothing, fallback. raw=%r",
            (raw or "")[:200],
        )
        return [base_query]

    # base_query 永远第一位; 然后追加 candidates 去重 (大小写不敏感)
    merged = _dedupe_preserve_order([base_query, *candidates])

    # 截断到 n 个 (原 + 至多 n-1 个 LLM 生成)
    return merged[:n]


# ─── RRF 融合 ─────────────────────────────────────────────────

def reciprocal_rank_fusion(
    rankings: list[list[dict]],
    *,
    id_key: str = "openalex_id",
    k: int = RRF_K,
    top_k: int = DEFAULT_FINAL_TOP_K,
) -> list[dict]:
    """RRF 融合多路排序.

    输入: [[doc, doc, ...], [doc, doc, ...], ...]  每路按相关性已排序 (rank 0 = 最相关)
    输出: 按融合分降序的 top_k 文档. 每个文档新增字段:
      - 'rrf_score' (float): 累积 RRF 分
      - 'rrf_hits' (int): 命中几路

    公式: score(d) = sum_{{i in rankings}} 1 / (k + rank_i(d))

    去重以 id_key 为键; 同一文档遇多路保留首次见到的完整 payload.
    缺失 id_key 的 doc 跳过 (无法去重).
    """
    if not rankings:
        return []

    fused: dict[str, dict[str, Any]] = {}

    for ranking in rankings:
        if not ranking:
            continue
        for rank, doc in enumerate(ranking):
            if not isinstance(doc, dict):
                continue
            doc_id = doc.get(id_key)
            if not doc_id:
                continue
            contribution = 1.0 / (k + rank)
            entry = fused.get(doc_id)
            if entry is None:
                # 浅拷贝, 不污染原 dict
                new_doc = dict(doc)
                new_doc["rrf_score"] = contribution
                new_doc["rrf_hits"] = 1
                fused[doc_id] = new_doc
            else:
                entry["rrf_score"] += contribution
                entry["rrf_hits"] += 1

    # 按 rrf_score 降序
    sorted_docs = sorted(fused.values(), key=lambda d: d["rrf_score"], reverse=True)
    return sorted_docs[:top_k]


# ─── 端到端 smart_retrieve ────────────────────────────────────

async def smart_retrieve(
    base_query: str,
    search_index,
    llm_manager,
    *,
    n_queries: int = DEFAULT_DIVERSE_COUNT,
    per_query_limit: int = DEFAULT_PER_QUERY_LIMIT,
    final_top_k: int = DEFAULT_FINAL_TOP_K,
    year_from: int | None = None,
    year_to: int | None = None,
    domain_hint: str | None = None,
    enabled: bool = True,
) -> dict:
    """端到端: query → diverse → 并行 BM25 → RRF → top-K.

    返回 envelope:
        {
            "docs": list[dict],          # 融合后的 top-K (含 rrf_score / rrf_hits)
            "queries_used": list[str],   # 实际使用的 query 列表
            "per_query_counts": dict,    # {query: hits} 便于诊断
            "smart_enabled": bool,       # 是否真的走了 smart 路径
            "fallback_reason": str|None, # 若降级到单 query 的原因
        }

    enabled=False 或 LLM 不可用 → 走单 query 路径 (向后兼容 + feature flag).
    任何 LLM/检索异常都降级到单 query, 不让上层炸掉.
    """
    base_query = (base_query or "").strip()

    # 边界: 空 query
    if not base_query:
        return {
            "docs": [],
            "queries_used": [],
            "per_query_counts": {},
            "smart_enabled": False,
            "fallback_reason": "empty_query",
        }

    # ─── 单 query 路径: feature flag off / 无 LLM ───
    fallback_reason: str | None = None
    if not enabled:
        fallback_reason = "feature_flag_off"
    elif llm_manager is None:
        fallback_reason = "no_llm_manager"
    elif n_queries <= 1:
        fallback_reason = "n_queries_le_1"

    if fallback_reason is not None:
        single_docs = await _safe_search(
            search_index, base_query, per_query_limit, year_from, year_to,
        )
        # 单路也走 RRF (一致接口, 加 rrf_score / rrf_hits)
        fused = reciprocal_rank_fusion(
            [single_docs], id_key="openalex_id", top_k=final_top_k,
        )
        return {
            "docs": fused,
            "queries_used": [base_query],
            "per_query_counts": {base_query: len(single_docs)},
            "smart_enabled": False,
            "fallback_reason": fallback_reason,
        }

    # ─── 多路 smart 路径 ───
    try:
        queries = await generate_diverse_queries(
            base_query, llm_manager,
            n=n_queries, domain_hint=domain_hint,
        )
    except Exception as e:
        logger.warning("[smart_retrieve] diverse stage crashed: %s", e)
        queries = [base_query]

    # 至少 base_query, 防御性保护
    if not queries:
        queries = [base_query]

    # 如果 LLM 没 diverse 出新 query (只有 base_query), 标记为部分降级但仍跑流程
    only_one = len(queries) == 1
    fallback_reason = "diverse_returned_only_base" if only_one else None

    # 并行检索 (search_index.search 是同步, 用 to_thread 并发)
    try:
        rankings = await asyncio.gather(
            *[
                _safe_search(search_index, q, per_query_limit, year_from, year_to)
                for q in queries
            ]
        )
    except Exception as e:
        logger.warning("[smart_retrieve] parallel BM25 crashed: %s — fallback single", e)
        rankings = [
            await _safe_search(search_index, base_query, per_query_limit, year_from, year_to)
        ]
        queries = [base_query]
        fallback_reason = "parallel_search_crash"

    per_query_counts = {q: len(r) for q, r in zip(queries, rankings)}

    fused = reciprocal_rank_fusion(
        rankings, id_key="openalex_id", top_k=final_top_k,
    )

    logger.info(
        "[smart_retrieve] base=%r diverse=%d total_hits=%d fused=%d",
        base_query[:60], len(queries), sum(per_query_counts.values()), len(fused),
    )

    return {
        "docs": fused,
        "queries_used": queries,
        "per_query_counts": per_query_counts,
        "smart_enabled": not only_one,
        "fallback_reason": fallback_reason,
    }


async def _safe_search(
    search_index,
    query: str,
    limit: int,
    year_from: int | None,
    year_to: int | None,
) -> list[dict]:
    """单路 BM25 调用, 异常吞掉返回 []. 用 to_thread 包同步 sqlite 调用."""
    if not query or not query.strip():
        return []
    try:
        return await asyncio.to_thread(
            search_index.search,
            query,
            limit,
            year_from,
            year_to,
        )
    except Exception as e:
        logger.warning("[smart_retrieve] BM25 single-query failed q=%r: %s", query[:60], e)
        return []


# ─── 自包含 smoke test (无 pytest 也能跑) ─────────────────────

async def _smoke_test() -> None:
    """模拟 LLM + SearchIndex, 验证三件事:
    1. RRF 数学正确
    2. LLM 失败降级到单 query
    3. enabled=False 走单 query
    """
    print("=" * 60)
    print("Smart Retriever — self-contained smoke test")
    print("=" * 60)

    # ── Test 1: RRF 数学 ──
    print("\n[Test 1] RRF math correctness")
    rankings = [
        # 路 1: rank0=A, rank1=B
        [{"openalex_id": "A", "title": "doc A"}, {"openalex_id": "B", "title": "doc B"}],
        # 路 2: rank0=B, rank1=C
        [{"openalex_id": "B", "title": "doc B"}, {"openalex_id": "C", "title": "doc C"}],
    ]
    # 手算 (k=60):
    #   A: 1/(60+0) = 1/60         ≈ 0.016667
    #   B: 1/(60+1) + 1/(60+0)     ≈ 0.016393 + 0.016667 = 0.033060
    #   C: 1/(60+1) = 1/61         ≈ 0.016393
    # 排序: B > A > C
    fused = reciprocal_rank_fusion(rankings, top_k=10)
    ids = [d["openalex_id"] for d in fused]
    assert ids == ["B", "A", "C"], f"expected [B,A,C], got {ids}"
    assert fused[0]["rrf_hits"] == 2, f"B should hit 2 paths, got {fused[0]['rrf_hits']}"
    assert fused[1]["rrf_hits"] == 1
    assert fused[2]["rrf_hits"] == 1
    expected_b = 1.0 / 61 + 1.0 / 60
    expected_a = 1.0 / 60
    expected_c = 1.0 / 61
    assert abs(fused[0]["rrf_score"] - expected_b) < 1e-9, \
        f"B score: expected {expected_b}, got {fused[0]['rrf_score']}"
    assert abs(fused[1]["rrf_score"] - expected_a) < 1e-9
    assert abs(fused[2]["rrf_score"] - expected_c) < 1e-9
    # A > C (A 在更前的 rank, 都只命中 1 路)
    assert fused[1]["rrf_score"] > fused[2]["rrf_score"]
    print(f"  PASS — RRF order=[B,A,C], B={expected_b:.6f} A={expected_a:.6f} C={expected_c:.6f}")

    # ── Test 2: LLM 失败 → fallback ──
    print("\n[Test 2] LLM failure → fallback to [base_query]")

    class _BadLLM:
        async def generate(self, *a, **k):
            raise RuntimeError("simulated LLM outage")

    out = await generate_diverse_queries("扩散模型", _BadLLM(), n=5)
    assert out == ["扩散模型"], f"expected fallback to [base], got {out}"
    print(f"  PASS — fallback to {out}")

    # LLM 返回 None
    class _NoneLLM:
        async def generate(self, *a, **k):
            return None
    out = await generate_diverse_queries("diffusion model", _NoneLLM(), n=5)
    assert out == ["diffusion model"]
    print("  PASS — None response also falls back")

    # LLM 返回非 JSON
    class _GarbageLLM:
        async def generate(self, *a, **k):
            return "I cannot help with that request."
    out = await generate_diverse_queries("foo", _GarbageLLM(), n=5)
    assert out == ["foo"]
    print("  PASS — non-JSON response falls back")

    # ── Test 3: enabled=False ──
    print("\n[Test 3] enabled=False → single-query path")

    class _FakeIndex:
        def search(self, q, limit=200, year_from=None, year_to=None):
            return [
                {"openalex_id": "X", "bm25_score": -10.5, "publication_year": 2024},
                {"openalex_id": "Y", "bm25_score": -8.2, "publication_year": 2023},
            ]

    class _UnusedLLM:
        async def generate(self, *a, **k):
            raise AssertionError("LLM should NOT be called when enabled=False")

    env = await smart_retrieve(
        "扩散模型", _FakeIndex(), _UnusedLLM(),
        enabled=False, final_top_k=10,
    )
    assert env["smart_enabled"] is False
    assert env["fallback_reason"] == "feature_flag_off"
    assert env["queries_used"] == ["扩散模型"]
    assert len(env["docs"]) == 2
    assert env["docs"][0]["openalex_id"] == "X"
    assert env["docs"][0]["rrf_hits"] == 1
    print(f"  PASS — single path, docs={len(env['docs'])}, reason={env['fallback_reason']}")

    # ── Test 4: 端到端 smart 路径 (mock LLM) ──
    print("\n[Test 4] end-to-end smart path with mock LLM")

    class _GoodLLM:
        calls = 0
        async def generate(self, prompt, **k):
            type(self).calls += 1
            return '{"queries": ["diffusion model", "score-based generative", "DDPM"]}'

    class _MultiIndex:
        def __init__(self):
            self.calls = []
        def search(self, q, limit=200, year_from=None, year_to=None):
            self.calls.append(q)
            # 不同 query 召回不同文档, 故意有重叠
            mapping = {
                "扩散模型": [{"openalex_id": "P1", "bm25_score": -10},
                             {"openalex_id": "P2", "bm25_score": -8}],
                "diffusion model": [{"openalex_id": "P2", "bm25_score": -12},
                                    {"openalex_id": "P3", "bm25_score": -9}],
                "score-based generative": [{"openalex_id": "P3", "bm25_score": -11},
                                            {"openalex_id": "P4", "bm25_score": -7}],
                "DDPM": [{"openalex_id": "P5", "bm25_score": -15}],
            }
            return mapping.get(q, [])

    idx = _MultiIndex()
    env = await smart_retrieve(
        "扩散模型", idx, _GoodLLM(),
        n_queries=5, final_top_k=10,
    )
    assert env["smart_enabled"] is True
    assert env["fallback_reason"] is None
    assert len(env["queries_used"]) == 4  # base + 3 diverse
    assert env["queries_used"][0] == "扩散模型"  # base 永远第一
    assert "diffusion model" in env["queries_used"]
    # P2 出现 2 次, P3 出现 2 次 → 应该排前面
    top_ids = [d["openalex_id"] for d in env["docs"][:2]]
    assert "P2" in top_ids and "P3" in top_ids, f"expected P2/P3 on top, got {top_ids}"
    print(f"  PASS — queries={env['queries_used']}, top2_ids={top_ids}")

    # ── Test 5: 边界 — 空 query ──
    print("\n[Test 5] empty query edge case")
    env = await smart_retrieve("", _MultiIndex(), _GoodLLM())
    assert env["fallback_reason"] == "empty_query"
    assert env["docs"] == []
    print("  PASS — empty query returns empty envelope")

    # ── Test 6: _safe_json_parse 各种格式 ──
    print("\n[Test 6] _safe_json_parse robustness")
    cases = [
        ('{"queries": ["a","b"]}', {"queries": ["a", "b"]}),
        ('```json\n{"queries":["x"]}\n```', {"queries": ["x"]}),
        ('here is json: {"queries":["y"]}', {"queries": ["y"]}),
        ('["foo","bar"]', ["foo", "bar"]),
        ('garbage text no json', None),
        ('', None),
        (None, None),
    ]
    for raw, expected in cases:
        got = _safe_json_parse(raw)
        assert got == expected, f"input={raw!r} expected={expected} got={got}"
    print(f"  PASS — {len(cases)} parse cases")

    print("\n" + "=" * 60)
    print("ALL SMOKE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_smoke_test())
