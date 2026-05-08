"""
KG Builder — Build and incrementally update the per-project knowledge graph.

Persistence: JSON (NetworkX node_link format) at data/knowledge_graphs/{project_id}.json
Called by graph_tasks.py Celery task when documents are classified.
"""
import logging
from pathlib import Path
from typing import Optional

from app.harness.knowledge_graph.store import KnowledgeGraphStore
from app.harness.knowledge_graph.extractor import extract_from_document

logger = logging.getLogger(__name__)

# Default data directory
KG_DATA_DIR = Path("/app/data/knowledge_graphs")


def get_kg_path(project_id: str) -> Path:
    """Get JSON path for a project's knowledge graph."""
    import os
    base = Path(os.environ.get("KG_DATA_DIR", str(KG_DATA_DIR)))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{project_id}.json"


def build_graph_for_document(
    project_id: str,
    doc: dict,
    bucket: str,
    llm_concepts: list[str] = None,
) -> dict:
    """
    Add/update a single document in the project's knowledge graph.

    Returns:
        stats dict {nodes_added, edges_added}
    """
    kg_path = get_kg_path(project_id)
    store = KnowledgeGraphStore(kg_path)

    try:
        nodes, edges = extract_from_document(doc, bucket, llm_concepts)

        if nodes:
            store.upsert_nodes(nodes)
        if edges:
            store.upsert_edges(edges)

        logger.info(
            "[KG Builder] project=%s doc=%s bucket=%s → %d nodes, %d edges",
            project_id[:8], str(doc.get("id", ""))[:8], bucket,
            len(nodes), len(edges),
        )

        return {"nodes_added": len(nodes), "edges_added": len(edges)}
    finally:
        store.close()


def rebuild_bucket(
    project_id: str,
    bucket: str,
    documents: list[dict],
) -> dict:
    """
    Rebuild the graph for an entire bucket.
    Clears existing bucket nodes, then re-extracts from all documents.
    """
    kg_path = get_kg_path(project_id)
    store = KnowledgeGraphStore(kg_path)

    try:
        # 先保留所有 llm_inferred 和 cites 边 —— 不论端点是否在本次 bucket 里
        # 保险起见做防御性备份：extract_from_document 绝不会产出这两类，
        # 不保留就只能靠 enrich 重跑补回来
        preserved_edges: list[tuple] = []
        for u, v, data in store.G.edges(data=True):
            if data.get("llm_inferred") or data.get("edge_type") == "cites":
                preserved_edges.append((u, v, dict(data)))

        store.delete_nodes_by_bucket(bucket)

        total_nodes = 0
        total_edges = 0

        for doc in documents:
            nodes, edges = extract_from_document(doc, bucket)
            if nodes:
                store.upsert_nodes(nodes)
                total_nodes += len(nodes)
            if edges:
                store.upsert_edges(edges)
                total_edges += len(edges)

        # 回放被级联删除的 llm_inferred / cites 边（doc 节点 id 不变，端点匹配）
        replayed = 0
        for u, v, attrs in preserved_edges:
            if u in store.G.nodes and v in store.G.nodes:
                store.G.add_edge(u, v, **attrs)
                replayed += 1
        if replayed:
            logger.info(
                "[KG Builder] bucket=%s: replayed %d preserved llm/cites edges",
                bucket, replayed,
            )

        store.set_meta(f"bucket_{bucket}_count", str(len(documents)))

        logger.info(
            "[KG Builder] Rebuilt bucket=%s for project=%s: %d docs → %d nodes, %d edges",
            bucket, project_id[:8], len(documents), total_nodes, total_edges,
        )

        return {
            "documents": len(documents),
            "nodes_added": total_nodes,
            "edges_added": total_edges,
        }
    finally:
        store.close()


def get_graph_data(project_id: str, bucket: str = None) -> Optional[dict]:
    """
    Get graph data for frontend visualization.

    Returns:
        {nodes: [...], edges: [...], stats: {...}, communities: {...}} or None
    """
    kg_path = get_kg_path(project_id)
    if not kg_path.exists():
        return None

    store = KnowledgeGraphStore(kg_path)
    try:
        if bucket:
            # Bug fix (2026-04-18): concept/author 节点 upsert 时 bucket 属性被多 doc 覆盖，
            # 直接按 bucket 过滤只能拿到 document 节点 —— 导致视图上只剩孤立圆点、边全丢。
            # 正确逻辑：
            #   1) 按 bucket 筛 document 节点
            #   2) 找到所有连到这些 doc 的 edges（通过 doc）
            #   3) 拉回 edges 另一端的 concept/author/journal 邻居节点
            #   4) 返回 (doc ∪ 邻居) + 这些节点内的全部 edges
            doc_nodes = store.get_nodes(bucket=bucket, node_type="document", limit=500)
            doc_ids = {n["node_id"] for n in doc_nodes}
            if not doc_ids:
                return {
                    "nodes": [],
                    "edges": [],
                    "stats": store.stats(),
                    "communities": store.get_communities(),
                }

            all_edges = store.get_edges(limit=10000)
            # edges 一端连到这些 doc 就算相关
            doc_edges = [
                e for e in all_edges
                if e["source_id"] in doc_ids or e["target_id"] in doc_ids
            ]

            # 邻居 id（去掉 doc 自身）
            neighbor_ids: set = set()
            for e in doc_edges:
                neighbor_ids.add(e["source_id"])
                neighbor_ids.add(e["target_id"])
            neighbor_ids -= doc_ids

            # 拉所有节点中是邻居的那些（不再按 bucket 过滤邻居）
            all_nodes = store.get_nodes(limit=10000)
            neighbor_nodes = [n for n in all_nodes if n["node_id"] in neighbor_ids]

            # 全部可见节点 id
            visible_ids = doc_ids | neighbor_ids
            # 保留任何两端都可见的 edge（包含 neighbor-neighbor，利于连通）
            edges = [
                e for e in all_edges
                if e["source_id"] in visible_ids and e["target_id"] in visible_ids
            ]

            combined_nodes = doc_nodes + neighbor_nodes
            return {
                "nodes": [
                    {"id": n["node_id"], **{k: v for k, v in n.items() if k != "node_id"}}
                    for n in combined_nodes
                ],
                "edges": [
                    {"source": e["source_id"], "target": e["target_id"],
                     **{k: v for k, v in e.items() if k not in ("source_id", "target_id")}}
                    for e in edges
                ],
                "stats": store.stats(),
                "communities": store.get_communities(),
            }
        else:
            return store.to_dict()
    finally:
        store.close()
