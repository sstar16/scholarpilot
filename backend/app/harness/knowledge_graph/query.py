"""
KG query helpers for协作研究模式。

提供两个工具：
- load_candidate_entities(project_id) — 给 Stage 1 planning 看"有哪些实体可查"
- build_subgraph_for_queries(project_id, queries) — 给 Stage 2 answering 注入实际子图

故意不做 LLM 调用；只在内存 / JSON 里遍历 NetworkX。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.harness.knowledge_graph.builder import get_kg_path
from app.harness.knowledge_graph.store import KnowledgeGraphStore

logger = logging.getLogger(__name__)


# Stage 1 候选优先级：先 concept（信息密度最高），再 topic，最后 author / journal
_CANDIDATE_PRIORITY = ("concept", "topic", "author", "journal")
_CANDIDATE_CAP_TOTAL = 30
_CANDIDATE_CAP_PER_TYPE = 15

# Stage 2 subgraph 配额
_SUBGRAPH_MAX_ENTITIES = 8         # 最多查几个实体
_SUBGRAPH_MAX_NEIGHBORS_PER = 8    # 每实体邻居
_SUBGRAPH_DOC_LABEL_MAX = 80       # 文献 label 裁剪


def load_candidate_entities(project_id: str) -> List[Dict]:
    """
    返回 project KG 里可以被选来精查的实体清单。
    每项: {entity_id, label, node_type, degree}
    """
    kg_path = get_kg_path(project_id)
    if not kg_path.exists():
        return []

    store = KnowledgeGraphStore(kg_path)
    try:
        by_type: Dict[str, List[Dict]] = {t: [] for t in _CANDIDATE_PRIORITY}
        for nid, data in store.G.nodes(data=True):
            t = data.get("node_type")
            if t not in by_type:
                continue
            label = data.get("label") or nid
            deg = store.G.degree(nid)
            by_type[t].append({
                "entity_id": nid,
                "label": label,
                "node_type": t,
                "degree": int(deg),
            })

        # 按 degree 倒序，每类取前 N
        out: List[Dict] = []
        for t in _CANDIDATE_PRIORITY:
            items = sorted(by_type[t], key=lambda x: -x["degree"])[:_CANDIDATE_CAP_PER_TYPE]
            out.extend(items)
            if len(out) >= _CANDIDATE_CAP_TOTAL:
                break
        return out[:_CANDIDATE_CAP_TOTAL]
    finally:
        store.close()


def _resolve_entity_id(store: KnowledgeGraphStore, query_label: str) -> Optional[str]:
    """
    把用户/LLM 给的 label（可能是"概念A"或 "concept:概念a" 或小写）解析到真实 node_id。
    匹配顺序：精确 id → 精确 label → 大小写无关 label。
    """
    if query_label in store.G.nodes:
        return query_label
    q_low = query_label.strip().lower()
    for nid, data in store.G.nodes(data=True):
        lbl = (data.get("label") or "").lower()
        if lbl == q_low or nid.lower() == q_low:
            return nid
    return None


def build_subgraph_for_queries(
    project_id: str,
    queries: List[Dict],
) -> Dict:
    """
    queries = [{"entity": "...", "reason": "..."}, ...]

    返回 prompt-ready dict:
        {
          "entities": [{"label": "...", "node_type": "...", "reason": "...",
                        "neighbors": [{"label": "...", "node_type": "...", "edge_type": "..."}]}],
          "missed": ["原样 label ..."]
        }
    若 queries 空，返回 {"entities": [], "missed": []}
    """
    if not queries:
        return {"entities": [], "missed": []}

    kg_path = get_kg_path(project_id)
    if not kg_path.exists():
        return {"entities": [], "missed": [q.get("entity", "") for q in queries]}

    store = KnowledgeGraphStore(kg_path)
    try:
        entities_out: List[Dict] = []
        missed: List[str] = []
        seen: set = set()

        for q in queries[:_SUBGRAPH_MAX_ENTITIES]:
            label = (q.get("entity") or "").strip()
            reason = (q.get("reason") or "").strip()
            if not label:
                continue
            nid = _resolve_entity_id(store, label)
            if not nid or nid in seen:
                if not nid:
                    missed.append(label)
                continue
            seen.add(nid)

            node_data = store.G.nodes[nid]
            neighbors: List[Dict] = []
            for nb in list(store.G.neighbors(nid))[:_SUBGRAPH_MAX_NEIGHBORS_PER]:
                nb_data = store.G.nodes[nb]
                edge = store.G[nid][nb] or {}
                nb_label = nb_data.get("label") or nb
                # 文献节点特殊：label 裁剪（标题可能很长）
                if nb_data.get("node_type") == "document":
                    nb_label = nb_label[:_SUBGRAPH_DOC_LABEL_MAX]
                neighbors.append({
                    "label": nb_label,
                    "node_type": nb_data.get("node_type", "unknown"),
                    "edge_type": edge.get("edge_type", "related"),
                })

            entities_out.append({
                "label": node_data.get("label") or nid,
                "node_type": node_data.get("node_type", "unknown"),
                "reason": reason,
                "neighbors": neighbors,
            })

        return {"entities": entities_out, "missed": missed}
    finally:
        store.close()
