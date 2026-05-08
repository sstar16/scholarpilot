"""
KG Analyzer — Community detection, god nodes, surprising connections, gaps.

Pattern follows graphify: Louvain clustering (NetworkX built-in), topology-based analysis.
No external dependencies beyond networkx.
"""
import logging
from collections import defaultdict

import networkx as nx

from app.harness.knowledge_graph.store import KnowledgeGraphStore

logger = logging.getLogger(__name__)


def detect_communities(store: KnowledgeGraphStore, min_nodes: int = 5) -> dict[int, list[str]]:
    """
    Louvain community detection (graphify pattern).
    Falls back gracefully for small/empty graphs.

    Returns: {community_id: [node_ids]} sorted by size descending.
    """
    G = store.G
    if G.number_of_nodes() < min_nodes or G.number_of_edges() == 0:
        return {}

    # Remove isolates for clustering
    connected = [n for n in G.nodes() if G.degree(n) > 0]
    if len(connected) < min_nodes:
        return {}

    subgraph = G.subgraph(connected)

    try:
        communities_gen = nx.community.louvain_communities(
            subgraph, seed=42, threshold=1e-4
        )
    except Exception as e:
        logger.warning("[KG Analyzer] Louvain failed: %s, falling back to components", e)
        communities_gen = list(nx.connected_components(subgraph))

    # Sort by size descending, assign stable IDs
    sorted_comms = sorted(communities_gen, key=len, reverse=True)
    result: dict[int, list[str]] = {}
    assignments: list[tuple[int, str]] = []

    for cid, members in enumerate(sorted_comms):
        if len(members) < 2:
            continue
        member_list = sorted(members)
        result[cid] = member_list
        for nid in member_list:
            assignments.append((cid, nid))

    store.save_communities(assignments)

    logger.info(
        "[KG Analyzer] Louvain detected %d communities from %d connected nodes",
        len(result), len(connected),
    )
    return result


def find_god_nodes(store: KnowledgeGraphStore, top_k: int = 10) -> list[dict]:
    """
    Find god nodes — highest degree centrality entities (graphify pattern).
    Excludes file-type hubs, focuses on real entities (concepts, authors, topics).

    Returns: [{node_id, label, node_type, degree, community}, ...]
    """
    G = store.G
    if G.number_of_nodes() == 0:
        return []

    degree = dict(G.degree())

    # Sort by degree, excluding trivial nodes
    candidates = []
    for nid, deg in sorted(degree.items(), key=lambda x: -x[1]):
        data = G.nodes[nid]
        ntype = data.get("node_type", "")
        # Skip document nodes as hubs (they connect to everything by nature)
        if ntype == "document":
            continue
        candidates.append({
            "node_id": nid,
            "label": data.get("label", nid),
            "node_type": ntype,
            "degree": deg,
            "community": data.get("community"),
        })
        if len(candidates) >= top_k:
            break

    return candidates


def find_surprising_connections(store: KnowledgeGraphStore, top_k: int = 10) -> list[dict]:
    """
    Find surprising cross-community connections (graphify pattern).
    Edges that bridge different communities are architecturally interesting.

    Returns: [{source, target, relation, source_community, target_community}, ...]
    """
    G = store.G
    if G.number_of_nodes() == 0:
        return []

    surprises = []
    for u, v, data in G.edges(data=True):
        u_comm = G.nodes[u].get("community")
        v_comm = G.nodes[v].get("community")
        if u_comm is not None and v_comm is not None and u_comm != v_comm:
            confidence = data.get("confidence", "EXTRACTED")
            # Score: INFERRED connections across communities are most surprising
            score = {"INFERRED": 3, "AMBIGUOUS": 2, "EXTRACTED": 1}.get(confidence, 1)
            surprises.append({
                "source": u,
                "source_label": G.nodes[u].get("label", u),
                "target": v,
                "target_label": G.nodes[v].get("label", v),
                "relation": data.get("edge_type", "related"),
                "confidence": confidence,
                "source_community": u_comm,
                "target_community": v_comm,
                "score": score,
            })

    surprises.sort(key=lambda x: -x["score"])
    return surprises[:top_k]


def find_gaps(store: KnowledgeGraphStore, max_gaps: int = 10) -> list[dict]:
    """
    Find research gaps — isolated concepts, thin clusters, single-connection topics.

    Returns: [{concept, connections, suggestion}, ...]
    """
    G = store.G
    gaps = []

    # 1. Concepts with only 1 document connection
    for nid, data in G.nodes(data=True):
        if data.get("node_type") not in ("concept", "topic"):
            continue
        doc_neighbors = [
            nb for nb in G.neighbors(nid)
            if G.nodes[nb].get("node_type") == "document"
        ]
        if len(doc_neighbors) == 1:
            gaps.append({
                "concept": data.get("label", nid),
                "node_id": nid,
                "connections": len(doc_neighbors),
                "type": "isolated_concept",
                "suggestion": f"仅 1 篇文献涉及「{data.get('label', nid)}」，可能是研究空白或新兴方向",
            })

    # 2. Isolated nodes (degree 0-1, not documents)
    for nid, data in G.nodes(data=True):
        if data.get("node_type") == "document":
            continue
        if G.degree(nid) == 0:
            gaps.append({
                "concept": data.get("label", nid),
                "node_id": nid,
                "connections": 0,
                "type": "isolated_node",
                "suggestion": f"「{data.get('label', nid)}」完全孤立，缺少关联文献",
            })

    gaps.sort(key=lambda x: x["connections"])
    return gaps[:max_gaps]


# Legacy aliases for backward compatibility
find_hub_nodes = find_god_nodes
