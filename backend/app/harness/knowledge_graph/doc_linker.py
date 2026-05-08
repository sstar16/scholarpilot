"""
LLM-driven document → document 语义关系增强。

流程：
1. 找候选 doc 对 —— 按"共享 concept/topic/author/journal 数量"降序取 top N
2. 从 DB 取每 doc 的 title + summary + ai_key_points 作上下文
3. 批量 LLM 判断关系（extends / refutes / parallel / surveys / replicates / applies）
4. 三层兜底过滤后写入带 reason 的 doc_relation 边
"""
from __future__ import annotations

import json
import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.harness.knowledge_graph.builder import get_kg_path
from app.harness.knowledge_graph.store import KnowledgeGraphStore
from app.harness.prompts.doc_link import (
    VALID_DOC_EDGE_TYPES,
    build_doc_link_prompt,
)

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.6
_BATCH_SIZE = 8           # doc 对比 concept 对上下文更重，一次少点
_MAX_KEY_POINTS = 3
_MIN_REASON_LEN = 5
_MAX_REASON_LEN = 300


def _find_doc_pairs(
    store: KnowledgeGraphStore,
    limit: int = 15,
) -> List[Dict]:
    """
    枚举 document 对，按共享 concept/topic/author/journal 数降序。
    不共享元素但各自有邻居的对作为弱信号候选。
    跳过已有 llm_inferred 边 / cites 边的对。
    """
    G = store.G
    docs = [n for n, d in G.nodes(data=True) if d.get("node_type") == "document"]
    if len(docs) < 2:
        return []

    meta_of: Dict[str, set] = {}
    for d in docs:
        meta_of[d] = {
            nb for nb in G.neighbors(d)
            if G.nodes[nb].get("node_type") in {"concept", "topic", "author", "journal"}
        }

    # 跳过：已有 llm_inferred 或 cites 边的 doc 对
    existing_pairs: set = set()
    for u, v, data in G.edges(data=True):
        et = data.get("edge_type")
        if data.get("llm_inferred") or et == "cites":
            existing_pairs.add(frozenset([u, v]))

    shared_pairs: List[Dict] = []
    weak_pairs: List[Dict] = []
    seen: set = set()
    for i, a in enumerate(docs):
        for b in docs[i + 1:]:
            key = frozenset([a, b])
            if key in seen or key in existing_pairs:
                continue
            seen.add(key)
            shared = meta_of[a] & meta_of[b]
            if len(shared) >= 1:
                shared_pairs.append({
                    "doc_a_id": a,
                    "doc_b_id": b,
                    "shared_count": len(shared),
                })
            elif meta_of[a] and meta_of[b]:
                weak_pairs.append({
                    "doc_a_id": a,
                    "doc_b_id": b,
                    "shared_count": 0,
                    "signal": len(meta_of[a]) + len(meta_of[b]),
                })

    shared_pairs.sort(key=lambda x: -x["shared_count"])
    weak_pairs.sort(key=lambda x: -x.get("signal", 0))

    result = shared_pairs[:limit]
    if len(result) < limit:
        result.extend(weak_pairs[:limit - len(result)])
    return result


async def _fetch_doc_context(db, doc_nid: str) -> Optional[Dict]:
    """从 DB 按 doc:<uuid> 节点 ID 解析，返回 title/summary/key_points"""
    from sqlalchemy import select
    from app.models.document import Document

    if not doc_nid.startswith("doc:"):
        return None
    try:
        did = _uuid.UUID(doc_nid[4:])
    except Exception:
        return None

    r = await db.execute(select(Document).where(Document.id == did))
    d = r.scalar_one_or_none()
    if not d:
        return None
    return {
        "title": (d.title or "Unknown")[:120],
        "summary": (d.one_line_summary or (d.abstract or "")[:200]),
        "key_points": (d.ai_key_points or [])[:_MAX_KEY_POINTS],
    }


# ─── placeholder/garbage 识别 ───
_PLACEHOLDER_TOKENS = {
    "unknown", "none", "n/a", "na", "null", "undefined", "待定", "未知", "无",
}


def _is_placeholder_reason(text: str) -> bool:
    low = text.strip().lower()
    return low in _PLACEHOLDER_TOKENS


def _parse_llm_array(text: str, expected_n: int) -> List[Dict]:
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
    if not isinstance(item, dict):
        return {"abstain": True}
    if item.get("abstain") is True:
        return {"abstain": True}
    edge_type = item.get("edge_type")
    if edge_type not in VALID_DOC_EDGE_TYPES:
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


# ─── 主入口 ───

async def enrich_doc_relations(
    project_id: str,
    llm_manager,
    db,
    limit: int = 15,
) -> Dict:
    """
    Returns: {pairs, edges_written, reason?}
    """
    if not llm_manager:
        return {"pairs": 0, "edges_written": 0, "reason": "no_llm"}

    kg_path = get_kg_path(project_id)
    if not kg_path.exists():
        return {"pairs": 0, "edges_written": 0, "reason": "no_graph"}

    store = KnowledgeGraphStore(kg_path)
    try:
        candidates = _find_doc_pairs(store, limit=limit)
        if not candidates:
            return {"pairs": 0, "edges_written": 0, "reason": "no_candidates"}

        edges_written = 0

        for batch_start in range(0, len(candidates), _BATCH_SIZE):
            batch = candidates[batch_start:batch_start + _BATCH_SIZE]
            pairs_ctx: List[Dict] = []
            resolved_batch: List[Dict] = []
            for p in batch:
                a_ctx = await _fetch_doc_context(db, p["doc_a_id"])
                b_ctx = await _fetch_doc_context(db, p["doc_b_id"])
                if not a_ctx or not b_ctx:
                    continue
                pairs_ctx.append({"doc_a": a_ctx, "doc_b": b_ctx})
                resolved_batch.append(p)

            if not pairs_ctx:
                continue

            system, user = build_doc_link_prompt(pairs_ctx)
            combined = f"{system}\n\n---\n\n{user}"

            raw: Optional[str] = None
            try:
                raw = await llm_manager.generate(combined, temperature=0.15)
            except Exception as e:
                logger.warning("[doc_linker] LLM call failed: %s", e)

            parsed = _parse_llm_array(raw or "", expected_n=len(resolved_batch))

            for pair, rel in zip(resolved_batch, parsed):
                if rel.get("abstain"):
                    continue
                props = {
                    "confidence": "INFERRED",
                    "reason": rel["reason"],
                    "llm_inferred": True,
                    "llm_confidence": rel["confidence"],
                    "inferred_at": datetime.now(timezone.utc).isoformat(),
                }
                edge = (
                    pair["doc_a_id"],
                    pair["doc_b_id"],
                    rel["edge_type"],
                    rel["confidence"],
                    None,
                    json.dumps(props, ensure_ascii=False),
                )
                store.upsert_edges([edge])
                edges_written += 1

        store.save()
        logger.info(
            "[doc_linker] project=%s candidates=%d edges_written=%d",
            project_id[:8], len(candidates), edges_written,
        )
        return {"pairs": len(candidates), "edges_written": edges_written}
    finally:
        store.close()
