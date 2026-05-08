"""
LLM-driven concept → concept 语义关系增强。

流程：
1. 从 KG store 找出共享 ≥N 文献的 concept 对（已有 llm_inferred 边的跳过）
2. 取每 concept 所在文献的 one_line_summary 作为证据
3. 批量送 LLM 推理关系（一次 10 对一个 LLM 调用）
4. 三层解析兜底：字段白名单 + 占位符识别 + 置信度阈值
5. 写入 store 作为带 reason 的边
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.harness.knowledge_graph.builder import get_kg_path
from app.harness.knowledge_graph.store import KnowledgeGraphStore
from app.harness.prompts.concept_link import (
    VALID_EDGE_TYPES,
    build_concept_link_prompt,
)

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.5
_BATCH_SIZE = 10
_MAX_SUMMARIES_PER_CONCEPT = 4
_MIN_REASON_LEN = 5
_MAX_REASON_LEN = 300


def _find_candidate_pairs(
    store: KnowledgeGraphStore,
    min_shared: int = 1,
    limit: int = 20,
    include_cross_doc: bool = True,
) -> List[Dict]:
    """
    挑 concept 两两配对候选。
    - 同文献共享 ≥min_shared 的对优先（shared_count 降序）
    - 若 include_cross_doc=True 且 limit 还没填满，补跨文献对（两端各自都连 doc，
      但互不共享文献）。跨文献对按"两端 doc 数之和"降序当做弱信号
    - 跳过已有 llm_inferred 边的对
    """
    G = store.G
    concepts = [n for n, d in G.nodes(data=True) if d.get("node_type") == "concept"]
    if len(concepts) < 2:
        return []

    docs_of: Dict[str, set] = {}
    for c in concepts:
        docs_of[c] = {
            nb for nb in G.neighbors(c)
            if G.nodes[nb].get("node_type") == "document"
        }

    existing_llm_pairs: set = set()
    for u, v, data in G.edges(data=True):
        if data.get("llm_inferred"):
            existing_llm_pairs.add(frozenset([u, v]))

    same_doc: List[Dict] = []
    cross_doc: List[Dict] = []
    seen: set = set()
    for i, a in enumerate(concepts):
        if not docs_of[a]:
            continue
        for b in concepts[i + 1:]:
            if not docs_of[b]:
                continue
            key = frozenset([a, b])
            if key in seen or key in existing_llm_pairs:
                continue
            shared = docs_of[a] & docs_of[b]
            seen.add(key)
            if len(shared) >= min_shared:
                same_doc.append({
                    "concept_a_id": a,
                    "concept_b_id": b,
                    "shared": sorted(shared),
                    "shared_count": len(shared),
                    "cross_doc": False,
                })
            elif include_cross_doc:
                cross_doc.append({
                    "concept_a_id": a,
                    "concept_b_id": b,
                    "shared": [],
                    "shared_count": 0,
                    "cross_doc": True,
                    # 弱信号：两端各自的文献覆盖度
                    "signal": len(docs_of[a]) + len(docs_of[b]),
                })

    same_doc.sort(key=lambda x: -x["shared_count"])
    cross_doc.sort(key=lambda x: -x.get("signal", 0))

    # same_doc 填满 limit 配额；cross_doc 独立保留一份配额，避免被同文献吃掉
    result = same_doc[:limit]
    if include_cross_doc:
        cross_doc_quota = max(5, limit // 2)  # 至少 5，或 limit 的一半
        result.extend(cross_doc[:cross_doc_quota])
    return result


def _collect_doc_summaries(
    store: KnowledgeGraphStore,
    concept_id: str,
) -> List[str]:
    """拿 concept 连接的 doc 的 one_line_summary（存在 node.summary 字段）。"""
    G = store.G
    out: List[str] = []
    for nb in G.neighbors(concept_id):
        data = G.nodes[nb]
        if data.get("node_type") != "document":
            continue
        s = (data.get("summary") or "").strip()
        if s:
            out.append(s[:200])
        else:
            title = (data.get("label") or "").strip()
            if title:
                out.append(title[:120])
        if len(out) >= _MAX_SUMMARIES_PER_CONCEPT:
            break
    return out


# ─────── 占位符 / 垃圾输出识别 ───────

_PLACEHOLDER_TOKENS = {
    "unknown", "none", "n/a", "na", "null", "undefined", "待定", "未知", "无",
}


def _is_placeholder_reason(text: str) -> bool:
    low = text.strip().lower()
    return low in _PLACEHOLDER_TOKENS or low.startswith("xxx") or low.startswith("tbd")


def _parse_llm_array(text: str, expected_n: int) -> List[Dict]:
    """三层兜底解析 LLM 的 JSON 数组输出。不合格项归一化为 {'abstain': True}。"""
    if not text:
        return [{"abstain": True}] * expected_n

    m = re.search(r'\[[\s\S]+\]', text)
    if not m:
        return [{"abstain": True}] * expected_n
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return [{"abstain": True}] * expected_n
    if not isinstance(data, list):
        return [{"abstain": True}] * expected_n

    out: List[Dict] = []
    for item in data[:expected_n]:
        out.append(_validate_item(item))
    while len(out) < expected_n:
        out.append({"abstain": True})
    return out


def _validate_item(item) -> Dict:
    """单条 item 三层校验：字段白名单 / 占位符 / 置信度阈值。"""
    if not isinstance(item, dict):
        return {"abstain": True}
    if item.get("abstain") is True:
        return {"abstain": True}

    edge_type = item.get("edge_type")
    if edge_type not in VALID_EDGE_TYPES:
        return {"abstain": True}

    reason = item.get("reason")
    if not isinstance(reason, str):
        return {"abstain": True}
    reason = reason.strip()
    if len(reason) < _MIN_REASON_LEN or _is_placeholder_reason(reason):
        return {"abstain": True}

    confidence = item.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        return {"abstain": True}
    conf = float(confidence)
    if conf < _CONFIDENCE_THRESHOLD:
        return {"abstain": True}

    return {
        "abstain": False,
        "edge_type": edge_type,
        "reason": reason[:_MAX_REASON_LEN],
        "confidence": max(0.0, min(1.0, conf)),
    }


# ─────── 主入口 ───────

async def enrich_concept_edges(
    project_id: str,
    llm_manager,
    limit: int = 20,
    min_shared: int = 1,
) -> Dict:
    """
    主流程：查候选 → 批量调 LLM → 过滤 → 写边。
    min_shared=1 意味着即使只共现在 1 篇文献里也作为候选，因为同一篇里的多个
    ai_key_points 往往是强相关概念；按 shared_count 降序再 limit。
    Returns: {pairs, edges_written, reason?}
    """
    if not llm_manager:
        return {"pairs": 0, "edges_written": 0, "reason": "no_llm"}

    kg_path = get_kg_path(project_id)
    if not kg_path.exists():
        return {"pairs": 0, "edges_written": 0, "reason": "no_graph"}

    store = KnowledgeGraphStore(kg_path)
    try:
        candidates = _find_candidate_pairs(store, min_shared=min_shared, limit=limit)
        if not candidates:
            return {"pairs": 0, "edges_written": 0, "reason": "no_candidates"}

        edges_written = 0

        for batch_start in range(0, len(candidates), _BATCH_SIZE):
            batch = candidates[batch_start:batch_start + _BATCH_SIZE]
            pairs_ctx: List[Dict] = []
            for p in batch:
                a_label = store.G.nodes[p["concept_a_id"]].get(
                    "label", p["concept_a_id"],
                )
                b_label = store.G.nodes[p["concept_b_id"]].get(
                    "label", p["concept_b_id"],
                )
                pairs_ctx.append({
                    "concept_a": a_label,
                    "a_summaries": _collect_doc_summaries(store, p["concept_a_id"]),
                    "concept_b": b_label,
                    "b_summaries": _collect_doc_summaries(store, p["concept_b_id"]),
                })

            system, user = build_concept_link_prompt(pairs_ctx)
            combined = f"{system}\n\n---\n\n{user}"

            raw: Optional[str] = None
            try:
                raw = await llm_manager.generate(combined, temperature=0.15)
            except Exception as e:
                logger.warning("[concept_linker] LLM call failed: %s", e)

            parsed = _parse_llm_array(raw or "", expected_n=len(batch))

            for pair, rel in zip(batch, parsed):
                if rel.get("abstain"):
                    continue
                props = {
                    "confidence": "INFERRED",
                    "reason": rel["reason"],
                    "llm_inferred": True,
                    "llm_confidence": rel["confidence"],
                    "shared_docs": pair["shared"][:5],
                    "inferred_at": datetime.now(timezone.utc).isoformat(),
                }
                edge = (
                    pair["concept_a_id"],
                    pair["concept_b_id"],
                    rel["edge_type"],
                    rel["confidence"],
                    None,  # bucket
                    json.dumps(props, ensure_ascii=False),
                )
                store.upsert_edges([edge])
                edges_written += 1

        store.save()
        logger.info(
            "[concept_linker] project=%s candidates=%d edges_written=%d",
            project_id[:8], len(candidates), edges_written,
        )
        return {
            "pairs": len(candidates),
            "edges_written": edges_written,
        }
    finally:
        store.close()
