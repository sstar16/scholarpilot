"""Knowledge Graph API — 每桶知识图谱查询端点"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["knowledge_graph"])


@router.get("/{project_id}/graph")
async def get_project_graph(
    project_id: uuid.UUID,
    bucket: str = Query(
        None,
        description="Filter by bucket: very_relevant|relevant|uncertain|irrelevant|all. Empty/all = no filter (full project graph).",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取项目知识图谱数据（用于前端可视化）"""
    await _verify_project(project_id, current_user.id, db)

    from app.harness.knowledge_graph.builder import get_graph_data
    # Treat "all" or empty as "no filter"
    filter_bucket = bucket if bucket and bucket != "all" else None
    data = get_graph_data(str(project_id), bucket=filter_bucket)

    if data is None:
        return {"nodes": [], "edges": [], "stats": {}, "communities": {}}
    return data


@router.get("/{project_id}/graph/hubs")
async def get_hub_nodes(
    project_id: uuid.UUID,
    top_k: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取 god nodes（连接度最高的实体节点，graphify 模式）"""
    await _verify_project(project_id, current_user.id, db)

    from app.harness.knowledge_graph.builder import get_kg_path
    from app.harness.knowledge_graph.store import KnowledgeGraphStore
    from app.harness.knowledge_graph.analyzer import find_god_nodes

    kg_path = get_kg_path(str(project_id))
    if not kg_path.exists():
        return {"hubs": []}

    store = KnowledgeGraphStore(kg_path)
    try:
        return {"hubs": find_god_nodes(store, top_k)}
    finally:
        store.close()


@router.get("/{project_id}/graph/gaps")
async def get_research_gaps(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """识别研究空白"""
    await _verify_project(project_id, current_user.id, db)

    from app.harness.knowledge_graph.builder import get_kg_path
    from app.harness.knowledge_graph.store import KnowledgeGraphStore
    from app.harness.knowledge_graph.analyzer import find_gaps

    kg_path = get_kg_path(str(project_id))
    if not kg_path.exists():
        return {"gaps": []}

    store = KnowledgeGraphStore(kg_path)
    try:
        return {"gaps": find_gaps(store)}
    finally:
        store.close()


@router.get("/{project_id}/graph/surprises")
async def get_surprising_connections(
    project_id: uuid.UUID,
    top_k: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发现跨社区的意外连接（graphify 模式）"""
    await _verify_project(project_id, current_user.id, db)

    from app.harness.knowledge_graph.builder import get_kg_path
    from app.harness.knowledge_graph.store import KnowledgeGraphStore
    from app.harness.knowledge_graph.analyzer import find_surprising_connections

    kg_path = get_kg_path(str(project_id))
    if not kg_path.exists():
        return {"surprises": []}

    store = KnowledgeGraphStore(kg_path)
    try:
        return {"surprises": find_surprising_connections(store, top_k)}
    finally:
        store.close()


@router.get("/{project_id}/graph/entity/{entity_id}/documents")
async def get_documents_for_entity(
    project_id: uuid.UUID,
    entity_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    返回 KG 中与该实体（concept / author / topic / journal）相连的所有文献。
    前端 KnowledgeGraphView 点击节点时调用。
    """
    await _verify_project(project_id, current_user.id, db)

    from app.harness.knowledge_graph.builder import get_kg_path
    from app.harness.knowledge_graph.store import KnowledgeGraphStore
    from app.models.document import Document

    kg_path = get_kg_path(str(project_id))
    if not kg_path.exists():
        return {"entity": None, "documents": []}

    store = KnowledgeGraphStore(kg_path)
    try:
        G = store.G
        if entity_id not in G:
            raise HTTPException(status_code=404, detail=f"实体 {entity_id} 不存在于图中")

        entity_data = dict(G.nodes[entity_id])
        # 收集 doc: 前缀的邻居 + 它们的 edge_type
        doc_ids: list[uuid.UUID] = []
        doc_edges: dict[str, str] = {}   # doc_uuid_str → edge_type
        for nb in G.neighbors(entity_id):
            if not nb.startswith("doc:"):
                continue
            try:
                did = uuid.UUID(nb[4:])
            except Exception:
                continue
            edata = G.get_edge_data(entity_id, nb) or {}
            doc_edges[str(did)] = edata.get("edge_type", "connected")
            doc_ids.append(did)

        if not doc_ids:
            return {
                "entity": {
                    "entity_id": entity_id,
                    "label": entity_data.get("label"),
                    "node_type": entity_data.get("node_type"),
                },
                "documents": [],
            }

        res = await db.execute(
            select(Document).where(Document.id.in_(doc_ids[:200]))
        )
        docs = res.scalars().all()
        out: list[dict] = []
        for d in docs:
            out.append({
                "id": str(d.id),
                "title": d.title or "",
                "source": d.source,
                "doc_type": d.doc_type,
                "authors": d.authors,
                "publication_date": d.publication_date.isoformat() if d.publication_date else None,
                "journal": d.journal,
                "doi": d.doi,
                "url": d.url,
                "one_line_summary": d.effective_one_line_summary,
                "edge_type": doc_edges.get(str(d.id), "connected"),
            })
        return {
            "entity": {
                "entity_id": entity_id,
                "label": entity_data.get("label"),
                "node_type": entity_data.get("node_type"),
            },
            "documents": out,
        }
    finally:
        store.close()


@router.post("/{project_id}/graph/rebuild")
async def rebuild_project_graph(
    project_id: uuid.UUID,
    bucket: str = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发图谱重建 —— 自动 chain 三个 enrich 保证 llm_inferred 边完整。"""
    await _verify_project(project_id, current_user.id, db)

    from celery import chain
    from app.workers.graph_tasks import (
        rebuild_graph,
        enrich_concept_edges,
        enrich_citations,
        enrich_doc_relations,
    )
    normalized_bucket = bucket if bucket and bucket != "all" else None
    chain(
        rebuild_graph.si(str(project_id), normalized_bucket),
        enrich_concept_edges.si(str(project_id)),
        enrich_citations.si(str(project_id)),
        enrich_doc_relations.si(str(project_id)),
    ).apply_async()

    return {"status": "rebuilding", "message": "图谱重建任务已提交（串行：rebuild → concept → citations → doc）"}


@router.post("/{project_id}/graph/enrich")
async def enrich_project_graph(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    手动触发图谱增强：
    - A: LLM 给共现 concept 对推理语义关系（带 reason 的边）
    - B: Crossref 拉引用关系（cites 边）
    """
    await _verify_project(project_id, current_user.id, db)

    from celery import chain
    from app.workers.graph_tasks import (
        enrich_concept_edges,
        enrich_citations,
        enrich_doc_relations,
    )
    # 串行：三个任务都会 load/save 同一 JSON，并发会互相覆盖
    chain(
        enrich_concept_edges.si(str(project_id)),
        enrich_citations.si(str(project_id)),
        enrich_doc_relations.si(str(project_id)),
    ).apply_async()

    return {
        "status": "enriching",
        "message": "已派发 concept 关联 → 引用抓取 → 文献语义关联 串行链",
    }


async def _verify_project(project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")
