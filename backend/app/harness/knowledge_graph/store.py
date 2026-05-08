"""
KnowledgeGraphStore — NetworkX-based per-project knowledge graph.

Persistence: JSON (node_link format) at data/knowledge_graphs/{project_id}.json
Pattern follows graphify: NetworkX graph + Louvain clustering + JSON export.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import networkx as nx
from networkx.readwrite import json_graph

logger = logging.getLogger(__name__)


class KnowledgeGraphStore:
    """NetworkX-backed per-project knowledge graph with JSON persistence."""

    def __init__(self, json_path: Path) -> None:
        self._path = json_path
        self._G: Optional[nx.Graph] = None

    # ------------------------------------------------------------------
    # Graph access
    # ------------------------------------------------------------------

    @property
    def G(self) -> nx.Graph:
        if self._G is None:
            self._G = self._load()
        return self._G

    def _load(self) -> nx.Graph:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # NetworkX 3.4+ 写入用 "edges" 键但读取默认仍找 "links" —— 显式兼容
                edges_key = "edges" if "edges" in data else "links"
                return json_graph.node_link_graph(data, edges=edges_key)
            except Exception as e:
                logger.warning("[KGStore] Failed to load %s: %s", self._path, e)
        return nx.Graph()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 显式指定 edges="edges" 与 networkx 3.6+ 写入默认一致，避免读写不对称丢边
        data = json_graph.node_link_data(self.G, edges="edges")
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def close(self) -> None:
        """Save and release graph."""
        if self._G is not None:
            self.save()
            self._G = None

    # ------------------------------------------------------------------
    # Node/edge operations
    # ------------------------------------------------------------------

    def add_node(self, node_id: str, **attrs) -> None:
        self.G.add_node(node_id, **attrs)

    def add_edge(self, src: str, tgt: str, **attrs) -> None:
        self.G.add_edge(src, tgt, **attrs)

    def upsert_nodes(self, nodes: list[tuple]) -> None:
        """Batch add nodes: [(node_id, node_type, label, bucket, properties_json)]"""
        for row in nodes:
            nid, ntype, label, bucket, props_json = row
            props = json.loads(props_json) if isinstance(props_json, str) else (props_json or {})
            self.G.add_node(nid, node_type=ntype, label=label, bucket=bucket, **props)

    def upsert_edges(self, edges: list[tuple]) -> None:
        """Batch add edges: [(src, tgt, edge_type, weight, bucket, properties_json)]"""
        for row in edges:
            src, tgt, etype, weight, bucket, props_json = row
            props = json.loads(props_json) if isinstance(props_json, str) else (props_json or {})
            self.G.add_edge(src, tgt, edge_type=etype, weight=weight, bucket=bucket, **props)

    def delete_nodes_by_bucket(self, bucket: str) -> None:
        to_remove = [n for n, d in self.G.nodes(data=True) if d.get("bucket") == bucket]
        self.G.remove_nodes_from(to_remove)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        return self.G.number_of_nodes()

    def edge_count(self) -> int:
        return self.G.number_of_edges()

    def get_nodes(self, bucket: str = None, node_type: str = None, limit: int = 500) -> list[dict]:
        result = []
        for nid, data in self.G.nodes(data=True):
            if bucket and data.get("bucket") != bucket:
                continue
            if node_type and data.get("node_type") != node_type:
                continue
            result.append({"node_id": nid, **data})
            if len(result) >= limit:
                break
        return result

    def get_edges(self, bucket: str = None, limit: int = 1000) -> list[dict]:
        result = []
        for u, v, data in self.G.edges(data=True):
            if bucket and data.get("bucket") != bucket:
                continue
            result.append({"source_id": u, "target_id": v, **data})
            if len(result) >= limit:
                break
        return result

    def get_neighbors(self, node_id: str, limit: int = 50) -> list[dict]:
        if node_id not in self.G:
            return []
        neighbors = []
        for nb in list(self.G.neighbors(node_id))[:limit]:
            data = self.G.nodes[nb]
            neighbors.append({"node_id": nb, **data})
        return neighbors

    def stats(self) -> dict:
        type_counts: dict[str, int] = {}
        for _, data in self.G.nodes(data=True):
            t = data.get("node_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "node_types": type_counts,
            "connected_components": nx.number_connected_components(self.G) if self.G.number_of_nodes() > 0 else 0,
        }

    # ------------------------------------------------------------------
    # Community helpers (set by analyzer)
    # ------------------------------------------------------------------

    def save_communities(self, assignments: list[tuple[int, str]]) -> None:
        """Save community assignments: [(community_id, node_id)]"""
        for cid, nid in assignments:
            if nid in self.G:
                self.G.nodes[nid]["community"] = cid

    def get_communities(self) -> dict[int, list[str]]:
        communities: dict[int, list[str]] = {}
        for nid, data in self.G.nodes(data=True):
            cid = data.get("community")
            if cid is not None:
                communities.setdefault(cid, []).append(nid)
        return communities

    def set_meta(self, key: str, value: str) -> None:
        self.G.graph[key] = value

    def get_meta(self, key: str) -> Optional[str]:
        return self.G.graph.get(key)

    # ------------------------------------------------------------------
    # Export (graphify-style)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Export graph as frontend-friendly dict."""
        nodes = []
        for nid, data in self.G.nodes(data=True):
            nodes.append({"id": nid, **data})

        edges = []
        for u, v, data in self.G.edges(data=True):
            edges.append({"source": u, "target": v, **data})

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": self.stats(),
            "communities": self.get_communities(),
        }
