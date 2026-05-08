"""
KG Extractor — Extract nodes and edges from Document + Classification data.

Tiered richness by bucket (unchanged).
Added: confidence labels (EXTRACTED / INFERRED) following graphify pattern.
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Node type constants
DOC = "document"
AUTHOR = "author"
TOPIC = "topic"
CONCEPT = "concept"
JOURNAL = "journal"

# Confidence labels (graphify pattern)
EXTRACTED = "EXTRACTED"   # Direct from metadata
INFERRED = "INFERRED"     # Derived from abstract/keywords


def extract_from_document(
    doc: dict,
    bucket: str,
    llm_concepts: list[str] = None,
) -> tuple[list[tuple], list[tuple]]:
    """
    Extract nodes and edges from a single document.

    Returns:
        (nodes, edges)
        node: (node_id, node_type, label, bucket, properties_json)
        edge: (source_id, target_id, edge_type, weight, bucket, properties_json)
    """
    nodes: list[tuple] = []
    edges: list[tuple] = []
    doc_id = str(doc.get("id", ""))
    title = doc.get("title", "Unknown")

    # -- Document node (always) --
    doc_props = {
        "source": doc.get("source"),
        "doi": doc.get("doi"),
        "date": str(doc.get("publication_date", "")),
        "summary": (doc.get("one_line_summary") or "")[:200],
        "confidence": EXTRACTED,
    }
    nodes.append((f"doc:{doc_id}", DOC, title[:100], bucket, json.dumps(doc_props, ensure_ascii=False)))

    if bucket in ("uncertain", "irrelevant"):
        return nodes, edges

    # -- Authors (relevant + very_relevant) --
    authors_str = doc.get("authors") or ""
    authors = [a.strip() for a in re.split(r"[;,]", authors_str) if a.strip()]
    for author in authors[:10]:
        author_id = f"author:{author.lower()}"
        nodes.append((author_id, AUTHOR, author, None, json.dumps({"confidence": EXTRACTED})))
        edges.append((f"doc:{doc_id}", author_id, "authored_by", 1.0, bucket,
                       json.dumps({"confidence": EXTRACTED})))

    # Co-authorship edges
    for i, a in enumerate(authors[:10]):
        for b in authors[i + 1:10]:
            a_id = f"author:{a.lower()}"
            b_id = f"author:{b.lower()}"
            edges.append((a_id, b_id, "co_authored", 1.0, bucket,
                           json.dumps({"confidence": EXTRACTED})))

    # -- Journal node --
    journal = doc.get("journal")
    if journal:
        j_id = f"journal:{journal.lower()[:80]}"
        nodes.append((j_id, JOURNAL, journal[:80], None, json.dumps({"confidence": EXTRACTED})))
        edges.append((f"doc:{doc_id}", j_id, "published_in", 1.0, bucket,
                       json.dumps({"confidence": EXTRACTED})))

    if bucket != "very_relevant":
        return nodes, edges

    # -- Concepts from LLM (very_relevant only) --
    concepts = llm_concepts or []

    # Fallback: extract concepts from ai_key_points
    if not concepts:
        key_points = doc.get("ai_key_points") or []
        for kp in key_points[:5]:
            if isinstance(kp, str) and len(kp) > 3:
                concepts.append(kp[:60])

    for concept in concepts[:15]:
        c_id = f"concept:{concept.lower()[:60]}"
        # Concepts from LLM key points are INFERRED
        nodes.append((c_id, CONCEPT, concept[:60], None, json.dumps({"confidence": INFERRED})))
        edges.append((f"doc:{doc_id}", c_id, "discusses", 1.0, bucket,
                       json.dumps({"confidence": INFERRED})))

    # -- Topic nodes from abstract keywords --
    abstract = doc.get("abstract") or ""
    if abstract and len(abstract) > 20:
        for word in _extract_topic_words(abstract):
            t_id = f"topic:{word.lower()}"
            nodes.append((t_id, TOPIC, word, None, json.dumps({"confidence": INFERRED})))
            edges.append((f"doc:{doc_id}", t_id, "relates_to", 0.5, bucket,
                           json.dumps({"confidence": INFERRED})))

    return nodes, edges


def extract_citation_edges(
    doc_id: str,
    cited_doc_ids: list[str],
    bucket: str,
) -> list[tuple]:
    """Create citation edges between documents."""
    return [
        (f"doc:{doc_id}", f"doc:{cited}", "cites", 1.0, bucket,
         json.dumps({"confidence": EXTRACTED}))
        for cited in cited_doc_ids
    ]


def _extract_topic_words(text: str, max_topics: int = 5) -> list[str]:
    """Simple keyword extraction from abstract (no LLM needed)."""
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "are", "was",
        "were", "been", "have", "has", "had", "not", "but", "can", "will",
        "our", "their", "its", "than", "also", "into", "such", "these",
        "which", "may", "both", "between", "through", "after", "about",
        "using", "used", "based", "results", "study", "method", "paper",
    }
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: -x[1])
    return [w for w, _ in sorted_words[:max_topics]]
