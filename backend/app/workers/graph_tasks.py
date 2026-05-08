"""
Celery tasks for knowledge graph building and updating.
Triggered asynchronously when documents are classified into buckets.
"""
import asyncio
import logging
import uuid

from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.workers.graph_tasks.update_graph_for_document", bind=True, max_retries=1)
def update_graph_for_document(self, project_id: str, document_id: str, bucket: str):
    """Update the knowledge graph when a single document is classified."""
    return _run_async(_update_graph_async(project_id, document_id, bucket))


@celery_app.task(name="app.workers.graph_tasks.rebuild_graph", bind=True, max_retries=1)
def rebuild_graph(self, project_id: str, bucket: str = None):
    """Rebuild the entire graph (or a single bucket) for a project."""
    return _run_async(_rebuild_graph_async(project_id, bucket))


async def _update_graph_async(project_id: str, document_id: str, bucket: str):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.harness.knowledge_graph.builder import build_graph_for_document, get_kg_path
    from app.harness.knowledge_graph.store import KnowledgeGraphStore
    from app.harness.knowledge_graph.analyzer import detect_communities
    from app.services.literature_writer import LiteratureWriter, parse_frontmatter
    from app.harness.file_tools.registry import tool_registry

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            try:
                result = await db.execute(
                    select(Document).where(Document.id == uuid.UUID(document_id))
                )
                doc = result.scalar_one_or_none()
                if not doc:
                    return {"error": "Document not found"}

                doc_dict = {
                    "id": str(doc.id),
                    "title": doc.title,
                    "authors": doc.authors,
                    "abstract": doc.abstract,
                    "source": doc.source,
                    "doi": doc.doi,
                    "journal": doc.journal,
                    "publication_date": str(doc.publication_date) if doc.publication_date else None,
                    "ai_key_points": doc.ai_key_points,
                    "one_line_summary": doc.one_line_summary,
                }

                # [S1 NEW] 优先从 .md frontmatter 读结构化 concepts
                llm_concepts: list[str] | None = None
                writer = LiteratureWriter(project_id, tool_registry())
                try:
                    slug_map = await writer._load_slug_map()
                    entry = slug_map.get("entries", {}).get(document_id)
                    if entry and entry.get("slug"):
                        slug = entry["slug"]
                        rel = f"literature/{slug}.md"
                        if writer.sandbox.exists(rel):
                            md_text = writer.sandbox.read_text(rel)
                            fm, _ = parse_frontmatter(md_text)
                            llm_concepts = [
                                c["name"]
                                for c in (fm.get("concepts") or [])
                                if isinstance(c, dict) and c.get("name")
                            ]
                            if llm_concepts:
                                logger.info(
                                    "[KGMd] project=%s doc=%s concepts_count=%d",
                                    project_id[:8], document_id[:8], len(llm_concepts),
                                )
                except Exception as e:
                    logger.warning("[KGMd] read frontmatter failed: %s, fallback", e)

                stats = build_graph_for_document(
                    project_id, doc_dict, bucket, llm_concepts=llm_concepts
                )

                # [S1 NEW] 同步 .md frontmatter 的 bucket 字段
                try:
                    await writer.update_bucket(document_id, bucket)
                except Exception as e:
                    logger.warning("[LibWriter] bucket sync failed: %s", e)

                # Run community detection if enough nodes
                kg_path = get_kg_path(project_id)
                store = KnowledgeGraphStore(kg_path)
                try:
                    if store.node_count() >= 10:
                        detect_communities(store)
                finally:
                    store.close()

                return stats
            except Exception as e:
                logger.error("[GraphTask] update_graph failed: %s", e)
                return {"error": str(e)}
    finally:
        await engine.dispose()


async def _rebuild_graph_async(project_id: str, bucket: str = None):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, func
    from app.config import settings
    from app.models.document import Document
    from app.models.document_classification import DocumentClassification
    from app.models.round_document import RoundDocument
    from app.models.search_round import SearchRound
    from app.harness.knowledge_graph.builder import rebuild_bucket

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            try:
                # First check if any classifications exist for this project
                classif_count_result = await db.execute(
                    select(func.count()).select_from(DocumentClassification).where(
                        DocumentClassification.project_id == uuid.UUID(project_id)
                    )
                )
                classif_count = int(classif_count_result.scalar() or 0)

                total_stats = {}

                if classif_count == 0 and bucket is None:
                    # No classifications yet → build KG from all round documents,
                    # treat them all as "uncertain" bucket. This lets users see
                    # a KG before they've manually classified anything.
                    logger.info(
                        "[KG Rebuild] project=%s has no classifications, falling back to round_documents",
                        project_id[:8],
                    )
                    result = await db.execute(
                        select(Document)
                        .join(RoundDocument, RoundDocument.document_id == Document.id)
                        .join(SearchRound, SearchRound.id == RoundDocument.round_id)
                        .where(SearchRound.project_id == uuid.UUID(project_id))
                        .distinct()
                    )
                    docs = result.scalars().all()

                    doc_dicts = [
                        {
                            "id": str(d.id),
                            "title": d.title,
                            "authors": d.authors,
                            "abstract": d.abstract,
                            "source": d.source,
                            "doi": d.doi,
                            "journal": d.journal,
                            "publication_date": str(d.publication_date) if d.publication_date else None,
                            "ai_key_points": d.ai_key_points,
                            "one_line_summary": d.one_line_summary,
                            "concept_tags": getattr(d, "concept_tags", None),
                        }
                        for d in docs
                    ]

                    if doc_dicts:
                        stats = rebuild_bucket(project_id, "uncertain", doc_dicts)
                        total_stats["uncertain"] = stats
                else:
                    # Classifications exist → rebuild the specified bucket(s) from classification
                    buckets_to_rebuild = [bucket] if bucket else [
                        "very_relevant", "relevant", "uncertain", "irrelevant"
                    ]

                    for b in buckets_to_rebuild:
                        # Fetch classified documents for this bucket
                        result = await db.execute(
                            select(Document)
                            .join(DocumentClassification, DocumentClassification.document_id == Document.id)
                            .where(
                                DocumentClassification.project_id == uuid.UUID(project_id),
                                DocumentClassification.bucket == b,
                            )
                        )
                        docs = result.scalars().all()

                        doc_dicts = [
                            {
                                "id": str(d.id),
                                "title": d.title,
                                "authors": d.authors,
                                "abstract": d.abstract,
                                "source": d.source,
                                "doi": d.doi,
                                "journal": d.journal,
                                "publication_date": str(d.publication_date) if d.publication_date else None,
                                "ai_key_points": d.ai_key_points,
                                "one_line_summary": d.one_line_summary,
                                "concept_tags": getattr(d, "concept_tags", None),
                            }
                            for d in docs
                        ]

                        if doc_dicts:
                            stats = rebuild_bucket(project_id, b, doc_dicts)
                            total_stats[b] = stats

                # Community detection
                from app.harness.knowledge_graph.builder import get_kg_path
                from app.harness.knowledge_graph.store import KnowledgeGraphStore
                from app.harness.knowledge_graph.analyzer import detect_communities

                kg_path = get_kg_path(project_id)
                if kg_path.exists():
                    store = KnowledgeGraphStore(kg_path)
                    try:
                        if store.node_count() >= 10:
                            detect_communities(store)
                    finally:
                        store.close()

                return total_stats
            except Exception as e:
                logger.error("[GraphTask] rebuild_graph failed: %s", e)
                return {"error": str(e)}
    finally:
        await engine.dispose()


# ─────────────────────────────────────────────────────────────────
# A: LLM-driven concept → concept 关联
# ─────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.graph_tasks.enrich_concept_edges",
    bind=True, max_retries=1,
)
def enrich_concept_edges(self, project_id: str, limit: int = 10):
    """批量让 LLM 判断共现 concept 对之间的语义关系，写带 reason 的边。"""
    return _run_async(_enrich_concept_edges_async(project_id, limit))


async def _enrich_concept_edges_async(project_id: str, limit: int = 10) -> dict:
    from app.services.core.llm_config_store import get_llm_manager
    from app.harness.knowledge_graph.concept_linker import enrich_concept_edges as _do

    try:
        manager = await get_llm_manager()
    except Exception as e:
        return {"error": f"llm_manager unavailable: {e}"}

    try:
        return await _do(project_id, manager, limit=limit)
    except Exception as e:
        logger.error("[GraphTask] enrich_concept_edges failed: %s", e)
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────
# B: Crossref 引用抓取 + cites 边
# ─────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.graph_tasks.enrich_citations",
    bind=True, max_retries=1,
)
def enrich_citations(self, project_id: str):
    """对项目内有 DOI 的文献调 Crossref，把引用关系连成 cites 边。"""
    return _run_async(_enrich_citations_async(project_id))


# ─────────────────────────────────────────────────────────────────
# C: LLM-driven document → document 语义关联
# ─────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.graph_tasks.enrich_doc_relations",
    bind=True, max_retries=1,
)
def enrich_doc_relations(self, project_id: str, limit: int = 15):
    """批量让 LLM 判断共享元素的 doc 对之间的语义关系（extends/surveys/refutes/...）"""
    return _run_async(_enrich_doc_relations_async(project_id, limit))


async def _enrich_doc_relations_async(project_id: str, limit: int = 15) -> dict:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.config import settings
    from app.services.core.llm_config_store import get_llm_manager
    from app.harness.knowledge_graph.doc_linker import enrich_doc_relations as _do

    try:
        manager = await get_llm_manager()
    except Exception as e:
        return {"error": f"llm_manager unavailable: {e}"}

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as db:
            try:
                return await _do(project_id, manager, db, limit=limit)
            except Exception as e:
                logger.error("[GraphTask] enrich_doc_relations failed: %s", e)
                return {"error": str(e)}
    finally:
        await engine.dispose()


async def _enrich_citations_async(project_id: str) -> dict:
    import json as _json
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.document_classification import DocumentClassification
    from app.services.citation_fetcher import fetch_references_dois
    from app.harness.knowledge_graph.builder import get_kg_path
    from app.harness.knowledge_graph.store import KnowledgeGraphStore

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            # 本项目已分类、有 DOI 的 document（去重）
            res = await db.execute(
                select(Document)
                .join(
                    DocumentClassification,
                    DocumentClassification.document_id == Document.id,
                )
                .where(
                    DocumentClassification.project_id == uuid.UUID(project_id),
                    Document.doi.isnot(None),
                )
                .distinct()
            )
            docs = list(res.scalars().all())
            if not docs:
                return {"docs": 0, "edges_written": 0, "reason": "no_doc_with_doi"}

            # 本项目内 DOI → doc_id 映射（用于把 Crossref 返回的 ref_doi 锚到项目内文献）
            doi_to_doc_id: dict[str, str] = {}
            for d in docs:
                if d.doi:
                    doi_to_doc_id[d.doi.strip().lower()] = str(d.id)

            kg_path = get_kg_path(project_id)
            if not kg_path.exists():
                return {"docs": len(docs), "edges_written": 0, "reason": "no_graph"}

            store = KnowledgeGraphStore(kg_path)
            edges_to_write: list[tuple] = []
            seen_edge: set = set()

            try:
                for d in docs:
                    ref_dois = await fetch_references_dois(d.doi)
                    if not ref_dois:
                        continue
                    src_nid = f"doc:{d.id}"
                    for ref_doi in ref_dois:
                        tgt_doc_id = doi_to_doc_id.get(ref_doi)
                        if not tgt_doc_id:
                            continue  # 不在项目内的引用暂不建边
                        tgt_nid = f"doc:{tgt_doc_id}"
                        if src_nid == tgt_nid:
                            continue
                        key = (src_nid, tgt_nid)
                        if key in seen_edge:
                            continue
                        seen_edge.add(key)
                        edges_to_write.append((
                            src_nid, tgt_nid, "cites", 1.0, None,
                            _json.dumps({
                                "confidence": "EXTRACTED",
                                "source": "crossref",
                            }),
                        ))

                if edges_to_write:
                    store.upsert_edges(edges_to_write)
                    store.save()

                logger.info(
                    "[GraphTask] enrich_citations project=%s docs=%d edges=%d",
                    project_id[:8], len(docs), len(edges_to_write),
                )
                return {
                    "docs": len(docs),
                    "edges_written": len(edges_to_write),
                }
            finally:
                store.close()
    except Exception as e:
        logger.error("[GraphTask] enrich_citations failed: %s", e)
        return {"error": str(e)}
    finally:
        await engine.dispose()
