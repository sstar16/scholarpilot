"""
Collaboration API — 协作研究模式端点。

用户在对话里说"帮我分析这些文献" → IntentAgent 识别 → 文献选择气泡 → 进入协作模式。
协作模式下用户不再检索，只在选定的文献集合内自由提问，AI 基于全文 + 摘要 + 图谱回答。
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.dependencies import get_current_user
from app.models.conversation_session import ConversationSession
from app.models.document import Document
from app.models.document_classification import DocumentClassification
from app.models.project import Project
from app.models.user import User
from app.services.conversation_inject import inject_rich_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversation", tags=["collaboration"])


# ──────────── Schemas ────────────

class StartCollaborationRequest(BaseModel):
    doc_ids: list[uuid.UUID]


class QuestionRequest(BaseModel):
    question: str


class UpdateDocsRequest(BaseModel):
    action: str  # add | remove | replace
    doc_ids: list[uuid.UUID]


class ExitCollaborationRequest(BaseModel):
    archive: bool = False


class NoteWriteRequest(BaseModel):
    content: str


class ResumePlanRequest(BaseModel):
    picks: list[dict] = []
    kg_queries: list[dict] = []
    auto_from_now: bool = False
    # 用户在 ReadPlanBubble 里勾选要用的探针节选 key，格式 "doc_id:section_idx"
    # 为空数组 = 用户没改（等价于"全选"，使用 pending_plan 里的所有探针）
    # None = 不用任何探针（退化回老行为：full_text[:8000]）
    selected_excerpt_keys: Optional[list[str]] = None


# ──────────── Helpers ────────────

async def _get_session_or_404(
    session_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> ConversationSession:
    res = await db.execute(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.user_id == user_id,
        )
    )
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="对话 session 不存在")
    return session


async def _load_docs_with_bucket(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    doc_ids: list[uuid.UUID],
) -> list[dict]:
    """Load documents with their bucket classifications."""
    if not doc_ids:
        return []

    # Join Document with DocumentClassification
    res = await db.execute(
        select(Document, DocumentClassification)
        .outerjoin(
            DocumentClassification,
            (DocumentClassification.document_id == Document.id)
            & (DocumentClassification.project_id == project_id)
            & (DocumentClassification.user_id == user_id),
        )
        .where(Document.id.in_(doc_ids))
    )
    rows = res.all()
    out = []
    for doc, cls in rows:
        out.append({
            "id": str(doc.id),
            "title": doc.title or "",
            "title_zh": doc.title_zh,
            "source": doc.source,
            "doc_type": doc.doc_type,
            "authors": doc.authors,
            "abstract": (doc.abstract or "")[:1000],
            "publication_date": doc.publication_date.isoformat() if doc.publication_date else None,
            "url": doc.url,
            "pdf_url": doc.pdf_url,
            "doi": doc.doi,
            "journal": doc.journal,
            # 卡片编辑合并：_user 优先，缺省 _ai。协作 prompt 和前端都拿到"有效值"
            "one_line_summary": doc.effective_one_line_summary,
            "ai_summary": doc.effective_ai_summary,
            "ai_key_points": doc.effective_ai_key_points,
            "ai_relevance_reason": doc.ai_relevance_reason,
            "ai_summary_source": doc.ai_summary_source,
            "user_edited_fields": doc.user_edited_fields,
            "quality_score": doc.quality_score,
            "fulltext_status": doc.fulltext_status,
            "fulltext_pdf_status": getattr(doc, "fulltext_pdf_status", None),
            "fulltext_html_status": getattr(doc, "fulltext_html_status", None),
            "fulltext_path": getattr(doc, "fulltext_path", None),
            "import_source": doc.import_source,
            "bucket": cls.bucket if cls else "uncertain",
            "has_fulltext": bool(doc.fulltext_text),
        })
    return out


async def _build_snapshot(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    doc_ids: list[uuid.UUID],
) -> dict:
    """Build the collaboration snapshot (docs + graph stats + memory)."""
    docs = await _load_docs_with_bucket(db, project_id, user_id, doc_ids)

    # Graph stats (best-effort)
    graph_nodes = 0
    try:
        from app.models.knowledge_graph import KnowledgeGraphCache
        res = await db.execute(
            select(KnowledgeGraphCache).where(
                KnowledgeGraphCache.project_id == project_id
            ).limit(1)
        )
        cache = res.scalar_one_or_none()
        if cache and isinstance(cache.data, dict):
            nodes = cache.data.get("nodes") or cache.data.get("entities") or []
            graph_nodes = len(nodes) if isinstance(nodes, list) else 0
    except Exception as e:
        logger.debug("[collab] graph cache unavailable: %s", e)

    # Memory sync timestamp
    memory_sync_at = None
    try:
        from app.models.user_profile import UserProfile
        res = await db.execute(
            select(UserProfile).where(
                UserProfile.user_id == user_id,
                UserProfile.project_id == project_id,
            )
        )
        profile = res.scalar_one_or_none()
        if profile and profile.updated_at:
            memory_sync_at = profile.updated_at.isoformat()
    except Exception as e:
        logger.debug("[collab] profile unavailable: %s", e)

    return {
        "docs": docs,
        "graph_nodes": graph_nodes,
        "memory_sync_at": memory_sync_at,
        "doc_count": len(docs),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _require_active_collaboration(session: ConversationSession) -> dict:
    state_data = session.state_data or {}
    collab = state_data.get("collaboration")
    if not collab or session.current_state != "collaboration_active" or collab.get("archived"):
        raise HTTPException(status_code=400, detail="当前不在协作模式中")
    return collab


# 可进入协作选择的前置 state（idle 或已经在选择中允许重选）
_STATES_ALLOWED_FOR_ENTER_COLLAB = {"idle", "collaboration_selecting"}
_STATE_ZH = {
    "intent_analysis": "意图解析",
    "intent_confirmation": "项目确认",
    "search_mode_selection": "选择检索方式",
    "keyword_confirmation": "关键词确认",
    "classification": "文献分类",
    "investigation": "检索进行中",
    "round_finalize": "本轮收尾",
    "collaboration_active": "协作研究",
}


def _assert_can_enter_collab(session: ConversationSession) -> None:
    """协作模式互斥守卫：检索流程进行中不允许切换到协作。"""
    st = session.current_state
    if st in _STATES_ALLOWED_FOR_ENTER_COLLAB:
        return
    zh = _STATE_ZH.get(st, st)
    raise HTTPException(
        status_code=409,
        detail=f"喵~当前正在「{zh}」流程里，要进协作研究得先把这条走完或点退出哦~",
    )


async def _assert_no_active_round(project_id, user_id, db: AsyncSession) -> None:
    """project 下有正在进行的检索轮次时，禁止进入协作模式。

    区分两类活跃 round:
    - "前期"态 (pending / awaiting_keywords / search_mode_selection)：如果没有任何 session
      处在对应的锁定态，就是孤儿（用户中途退出 / session 被清但 round 没清），自动 cancel
    - "执行中"态 (searching / scoring / awaiting_feedback)：必须拦住让用户先处理
    """
    from app.models.search_round import SearchRound
    from datetime import datetime, timezone
    EARLY_ROUND_STATUSES = ("pending", "awaiting_keywords", "search_mode_selection")
    RUNTIME_ROUND_STATUSES = ("searching", "scoring", "awaiting_feedback")

    # 先看执行中态 —— 有就必须拦
    res = await db.execute(
        select(SearchRound.status)
        .where(
            SearchRound.project_id == project_id,
            SearchRound.status.in_(RUNTIME_ROUND_STATUSES),
        )
        .limit(1)
    )
    active_status = res.scalar_one_or_none()

    # 前期态 → 仅当 project 下确有 session 卡在检索锁定态才拦；否则视为孤儿清理
    if active_status is None:
        LOCKED_SEARCH_STATES = (
            "intent_analysis", "intent_confirmation", "search_mode_selection",
            "keyword_confirmation", "searching", "scoring", "classification", "round_finalize",
        )
        locked_sess = await db.execute(
            select(ConversationSession.id)
            .where(
                ConversationSession.project_id == project_id,
                ConversationSession.user_id == user_id,
                ConversationSession.is_active == True,  # noqa: E712
                ConversationSession.current_state.in_(LOCKED_SEARCH_STATES),
            ).limit(1)
        )
        has_locked_session = locked_sess.scalar_one_or_none() is not None

        orphan_res = await db.execute(
            select(SearchRound).where(
                SearchRound.project_id == project_id,
                SearchRound.status.in_(EARLY_ROUND_STATUSES),
            )
        )
        orphans = list(orphan_res.scalars().all())
        if orphans and not has_locked_session:
            # 清理孤儿 round，让协作能进
            for r in orphans:
                r.status = "cancelled"
                r.cancelled_reason = "orphan_auto_cleanup"
                r.cancelled_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "[collab] 清理 %d 个孤儿 round (project=%s) after idle session detected",
                len(orphans), project_id,
            )
            active_status = None
        elif orphans and has_locked_session:
            active_status = orphans[0].status

    if active_status is None:
        return
    zh_map = {
        "pending": "准备检索", "awaiting_keywords": "等待确认关键词",
        "searching": "检索中", "scoring": "评分中", "awaiting_feedback": "等待分类反馈",
    }
    raise HTTPException(
        status_code=409,
        detail=f"喵~第一轮还在「{zh_map.get(active_status, active_status)}」呢，等本轮结束后再来协作嘛！",
    )


# ──────────── Endpoints ────────────

@router.post("/{session_id}/collaboration/start")
async def start_collaboration(
    session_id: uuid.UUID,
    req: StartCollaborationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enter collaboration mode with the selected documents."""
    session = await _get_session_or_404(session_id, current_user.id, db)
    if not session.project_id:
        raise HTTPException(status_code=400, detail="未关联项目")

    # 互斥守卫：只能从 collaboration_selecting 进入 active
    if session.current_state != "collaboration_selecting":
        zh = _STATE_ZH.get(session.current_state, session.current_state)
        raise HTTPException(
            status_code=409,
            detail=f"喵~要先通过「协作研究」按钮进入文献选择（当前是「{zh}」）",
        )

    if not req.doc_ids:
        raise HTTPException(status_code=400, detail="请至少选择一篇文献")

    # Build snapshot
    snapshot = await _build_snapshot(db, session.project_id, current_user.id, req.doc_ids)
    if not snapshot["docs"]:
        raise HTTPException(status_code=400, detail="选中的文献无法加载")

    # Persist collaboration state
    state_data = dict(session.state_data or {})
    state_data["collaboration"] = {
        "started_at": _now_iso(),
        "doc_ids": [str(d) for d in req.doc_ids],
        "snapshot_version": 1,
        "last_memory_sync": snapshot.get("memory_sync_at"),
        "archived": False,
    }
    session.state_data = state_data
    session.current_state = "collaboration_active"
    flag_modified(session, "state_data")

    # Inject banner-level rich message
    await inject_rich_message(
        db,
        session_id=session.id,
        rich_type="collaboration_started",
        content=f"已进入协作研究模式，{len(snapshot['docs'])} 篇文献参与分析",
        rich_data={
            "doc_count": len(snapshot["docs"]),
            "started_at": state_data["collaboration"]["started_at"],
        },
        commit=False,
    )
    await db.commit()

    logger.info(
        "[collab] start session=%s docs=%d", session.id, len(snapshot["docs"])
    )
    return {
        "state": "active",
        "doc_ids": state_data["collaboration"]["doc_ids"],
        "snapshot": snapshot,
    }


@router.post("/{session_id}/collaboration/question")
async def collaboration_question(
    session_id: uuid.UUID,
    req: QuestionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Answer a research question grounded in the selected documents."""
    session = await _get_session_or_404(session_id, current_user.id, db)
    collab = await _require_active_collaboration(session)

    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    doc_ids = [uuid.UUID(d) for d in collab.get("doc_ids", [])]
    if not doc_ids:
        raise HTTPException(status_code=400, detail="协作文献列表为空")

    # Append user question to history —— 但如果是从 conversation.py 的 /message 端点
    # 路由进来，那边已 _append_message 过一次，避免重复
    msgs = list(session.messages or [])
    last = msgs[-1] if msgs else None
    already_pushed = bool(
        last
        and last.get("role") == "user"
        and (last.get("content") or "") == question
    )
    if not already_pushed:
        msgs.append({
            "role": "user",
            "content": question,
            "timestamp": _now_iso(),
            "metadata": {"source": "collaboration"},
        })
        session.messages = msgs
        flag_modified(session, "messages")
    await db.commit()

    # Load candidate papers (摘要/要点；全文由 Agent 在 Stage 1 决定再按需加载)
    docs = await _load_docs_with_bucket(db, session.project_id, current_user.id, doc_ids)
    papers: list[dict] = []
    for doc in docs[:30]:
        papers.append({
            "id": doc["id"],
            "title": doc["title"],
            "authors": doc.get("authors"),
            "abstract": doc.get("abstract", ""),
            "one_line_summary": doc.get("one_line_summary"),
            "ai_key_points": doc.get("ai_key_points"),
            "ai_summary": doc.get("ai_summary"),
            "has_fulltext": bool(doc.get("has_fulltext")),
        })

    async def _fulltext_loader(doc_id_str: str) -> Optional[str]:
        try:
            did = uuid.UUID(doc_id_str)
        except Exception:
            return None
        r = await db.execute(
            select(Document.fulltext_text).where(Document.id == did)
        )
        return r.scalar_one_or_none()

    from app.harness.agents.research_agent import ResearchAgent
    from app.services.core.llm_config_store import get_llm_manager

    manager = await get_llm_manager()
    agent = ResearchAgent(llm_manager=manager)

    # Load project description for context
    proj_res = await db.execute(
        select(Project).where(Project.id == session.project_id)
    )
    proj = proj_res.scalar_one_or_none()

    # Load user memory (best effort)
    user_memory = ""
    try:
        from app.models.user_profile import UserProfile
        pr = await db.execute(
            select(UserProfile).where(
                UserProfile.user_id == current_user.id,
                UserProfile.project_id == session.project_id,
            )
        )
        profile = pr.scalar_one_or_none()
        if profile and profile.memory_text:
            user_memory = profile.memory_text[:1500]
    except Exception:
        pass

    history = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in msgs[-10:]
        if not m.get("rich_type")  # skip rich messages from history
    ]

    # ── 加载 KG 候选实体供 Stage 1 planning
    from app.harness.knowledge_graph.query import load_candidate_entities
    try:
        kg_candidates = load_candidate_entities(str(session.project_id))
    except Exception as e:
        logger.debug("[collab] kg candidates unavailable: %s", e)
        kg_candidates = []

    # ── Stage 1：LLM 规划（挑精读文献 + KG 实体）
    plan = await agent.plan(
        question=question,
        candidates=papers,
        kg_candidates=kg_candidates,
        max_reads=3,
        max_kg_queries=5,
    )
    picks = plan.get("picks") or []
    queries = plan.get("kg_queries") or []

    # ── Stage 1.5: 对 picks 跑探针（section 级精读 + 缓存）
    # 过去每次提问都对 full_text[:8000] 走 LLM；现在 Stage 1.5 按 section 切分并行探针，
    # 结果进 doc.probe_cache 跨提问复用。相似问题命中缓存 → 直接复用不调 LLM。
    probe_excerpts: list[dict] = []
    if picks:
        try:
            probe_excerpts = await _run_probes_for_picks(
                db=db,
                question=question,
                picks=picks,
                papers=papers,
                fulltext_loader=_fulltext_loader,
                llm_manager=manager,
            )
        except Exception as e:
            logger.warning("[collab] probes failed; will fallback to full_text: %s", e)
            probe_excerpts = []

    # ── 路由：auto_mode 或 LLM 没挑任何内容 → 直通 Stage 2；否则挂起等用户确认
    auto_mode = bool(collab.get("auto_mode"))
    if auto_mode or (not picks and not queries):
        logger.info(
            "[collab] auto-through Stage 2 (auto=%s picks=%d queries=%d excerpts=%d)",
            auto_mode, len(picks), len(queries), len(probe_excerpts),
        )
        return await _finalize_answer(
            db=db, session=session, proj=proj, question=question,
            papers=papers, picks=picks, queries=queries,
            fulltext_loader=_fulltext_loader,
            user_memory=user_memory, history=history, agent=agent,
            probe_excerpts=probe_excerpts or None,
        )

    # vibe：把计划存 session 并发 ReadPlanBubble，等用户 /resume
    candidates_snapshot = [
        {
            "id": p["id"],
            "title": p["title"],
            "has_fulltext": p.get("has_fulltext", False),
            "one_line_summary": p.get("one_line_summary"),
        }
        for p in papers
    ]
    state_data = dict(session.state_data or {})
    col = dict(state_data.get("collaboration") or {})
    col["pending_plan"] = {
        "question": question,
        "picks": picks,
        "kg_queries": queries,
        "candidates_snapshot": candidates_snapshot,
        "kg_candidates_snapshot": kg_candidates,
        "probes": probe_excerpts,
        "created_at": _now_iso(),
    }
    state_data["collaboration"] = col
    session.state_data = state_data
    flag_modified(session, "state_data")

    await inject_rich_message(
        db,
        session_id=session.id,
        rich_type="collaboration_read_plan",
        content=f"调研计划：精读 {len(picks)} 篇 + 展开 {len(queries)} 个实体 + 探针命中 {len(probe_excerpts)} 段",
        rich_data={
            "question": question,
            "picks": picks,
            "kg_queries": queries,
            "candidates": candidates_snapshot,
            "kg_candidates": kg_candidates,
            "probes": probe_excerpts,
        },
        commit=False,
    )
    await db.commit()

    return {
        "state": "awaiting_plan",
        "plan": {
            "picks": picks,
            "kg_queries": queries,
            "probes": probe_excerpts,
        },
    }


@router.post("/{session_id}/collaboration/update-docs")
async def update_collaboration_docs(
    session_id: uuid.UUID,
    req: UpdateDocsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Adjust the set of documents participating in the current collaboration."""
    session = await _get_session_or_404(session_id, current_user.id, db)
    collab = await _require_active_collaboration(session)

    if req.action not in ("add", "remove", "replace"):
        raise HTTPException(status_code=400, detail=f"无效的 action: {req.action}")

    current_ids: set[str] = set(collab.get("doc_ids", []))
    new_ids_str = {str(d) for d in req.doc_ids}

    if req.action == "add":
        current_ids |= new_ids_str
    elif req.action == "remove":
        current_ids -= new_ids_str
    else:  # replace
        current_ids = new_ids_str

    if not current_ids:
        raise HTTPException(status_code=400, detail="文献列表不能为空")

    doc_uuids = [uuid.UUID(d) for d in current_ids]
    snapshot = await _build_snapshot(db, session.project_id, current_user.id, doc_uuids)

    state_data = dict(session.state_data or {})
    state_data["collaboration"]["doc_ids"] = sorted(current_ids)
    state_data["collaboration"]["snapshot_version"] = collab.get("snapshot_version", 1) + 1
    session.state_data = state_data
    flag_modified(session, "state_data")
    await db.commit()

    return {
        "doc_ids": sorted(current_ids),
        "snapshot": snapshot,
    }


@router.post("/{session_id}/collaboration/refresh")
async def refresh_collaboration(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Refresh documents / memory / graph when re-entering a kept collaboration."""
    session = await _get_session_or_404(session_id, current_user.id, db)
    state_data = session.state_data or {}
    collab = state_data.get("collaboration")
    if not collab:
        raise HTTPException(status_code=400, detail="该 session 无协作记录")

    if collab.get("archived"):
        raise HTTPException(status_code=400, detail="该协作已归档，不可重新进入")

    doc_ids = [uuid.UUID(d) for d in collab.get("doc_ids", [])]
    snapshot = await _build_snapshot(db, session.project_id, current_user.id, doc_ids)

    # Update session with refreshed state
    new_sd = dict(state_data)
    new_sd["collaboration"]["last_memory_sync"] = snapshot.get("memory_sync_at") or _now_iso()
    new_sd["collaboration"]["snapshot_version"] = collab.get("snapshot_version", 1) + 1
    session.state_data = new_sd
    session.current_state = "collaboration_active"
    flag_modified(session, "state_data")
    await db.commit()

    return {
        "doc_ids": collab.get("doc_ids", []),
        "snapshot": snapshot,
        "refreshed_at": _now_iso(),
    }


@router.post("/{session_id}/collaboration/exit")
async def exit_collaboration(
    session_id: uuid.UUID,
    req: ExitCollaborationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exit collaboration mode. archive=True means permanent, False keeps it for re-entry."""
    session = await _get_session_or_404(session_id, current_user.id, db)
    state_data = dict(session.state_data or {})
    collab = state_data.get("collaboration")
    if not collab:
        raise HTTPException(status_code=400, detail="该 session 无协作记录")

    collab["archived"] = bool(req.archive)
    collab["ended_at"] = _now_iso()
    # 退出协作 → 清 auto_mode 和 pending_plan，下次进入重新进入 vibe 模式
    collab.pop("auto_mode", None)
    collab.pop("pending_plan", None)
    state_data["collaboration"] = collab
    session.state_data = state_data
    session.current_state = "idle"  # return to normal chat mode
    flag_modified(session, "state_data")

    await inject_rich_message(
        db,
        session_id=session.id,
        rich_type="collaboration_ended",
        content="协作模式已退出" + ("（已归档）" if req.archive else "（已保留，可重新进入）"),
        rich_data={
            "archived": bool(req.archive),
            "ended_at": collab["ended_at"],
            "doc_count": len(collab.get("doc_ids", [])),
        },
        commit=False,
    )
    await db.commit()

    return {"state": "idle", "archived": bool(req.archive)}


@router.post("/{session_id}/collaboration/suggest-scope")
async def suggest_scope(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Emit a collaboration_scope rich message asking the user to pick documents.
    Called by IntentAgent when it detects 'analyze_documents' intent.
    """
    session = await _get_session_or_404(session_id, current_user.id, db)
    if not session.project_id:
        raise HTTPException(status_code=400, detail="未关联项目")

    # 1) round-level 先判：project 有活跃 round 就拦
    await _assert_no_active_round(session.project_id, current_user.id, db)

    # 2) session-level 自修复：若 session 卡在检索锁定态但项目已无活跃 round，自动切回 idle
    LOCKED_SEARCH_STATES = (
        "intent_analysis", "intent_confirmation", "search_mode_selection",
        "keyword_confirmation", "searching", "scoring", "classification", "round_finalize",
    )
    if session.current_state in LOCKED_SEARCH_STATES:
        session.current_state = "idle"
        await db.commit()

    # 3) 再跑 session-level 互斥（此时锁定态已自修复，只会拦 collab_active 这种真正重叠情况）
    _assert_can_enter_collab(session)

    # Load all classified documents in the project
    res = await db.execute(
        select(Document, DocumentClassification.bucket)
        .join(
            DocumentClassification,
            DocumentClassification.document_id == Document.id,
        )
        .where(
            DocumentClassification.project_id == session.project_id,
            DocumentClassification.user_id == current_user.id,
        )
        .limit(100)
    )
    candidates = []
    for doc, bucket in res.all():
        candidates.append({
            "id": str(doc.id),
            "title": doc.title or "",
            "source": doc.source,
            "bucket": bucket or "uncertain",
            "one_line_summary": doc.one_line_summary,
            "fulltext_status": doc.fulltext_status,
        })

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail="文献库为空，请先完成至少一轮检索并分类后再进入协作模式",
        )

    session.current_state = "collaboration_selecting"
    flag_modified(session, "state_data")

    await inject_rich_message(
        db,
        session_id=session.id,
        rich_type="collaboration_scope",
        content=f"请选择协作要分析的文献（共 {len(candidates)} 篇可选）",
        rich_data={"candidate_docs": candidates},
    )

    return {"state": "collaboration_selecting", "candidate_count": len(candidates)}


# ──────────── Research Note Endpoints ────────────

@router.get("/{session_id}/collaboration/note")
async def get_research_note(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """读取当前 project 的共享研究笔记。不强制在协作态，便于退出后查看。"""
    session = await _get_session_or_404(session_id, current_user.id, db)
    if not session.project_id:
        raise HTTPException(status_code=400, detail="未关联项目")

    res = await db.execute(select(Project).where(Project.id == session.project_id))
    proj = res.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    return {
        "content": proj.research_note_md or "",
        "updated_at": proj.research_note_updated_at.isoformat()
        if proj.research_note_updated_at else None,
        "updated_by": proj.research_note_updated_by,
    }


@router.put("/{session_id}/collaboration/note")
async def update_research_note(
    session_id: uuid.UUID,
    req: NoteWriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户主动编辑/保存研究笔记。替换式写入。"""
    session = await _get_session_or_404(session_id, current_user.id, db)
    if not session.project_id:
        raise HTTPException(status_code=400, detail="未关联项目")

    res = await db.execute(select(Project).where(Project.id == session.project_id))
    proj = res.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 用户侧硬上限 200KB
    content = (req.content or "")[:200_000]
    proj.research_note_md = content
    proj.research_note_updated_at = datetime.now(timezone.utc)
    proj.research_note_updated_by = "user"
    flag_modified(proj, "research_note_md")
    await db.commit()

    return {
        "content": proj.research_note_md,
        "updated_at": proj.research_note_updated_at.isoformat(),
        "updated_by": proj.research_note_updated_by,
    }


# ──────────── Note-update helper ────────────

_NOTE_MAX_LEN = 200_000  # 单个 project 的笔记硬上限


async def _apply_note_update_to_notebook(
    db: AsyncSession,
    project_id: uuid.UUID,
    note_update: dict,
) -> Optional[dict]:
    """
    AI 的 note_update 已通过 _parse_note_update 校验：
      {mode: create_page|update_page|append_to_page, content, page_id?, title?, reason}
    根据 mode 写入 research_note_pages 表。返回应用摘要给前端展示。
    外层调用者负责 commit。
    """
    from sqlalchemy import func as _func
    from app.models.research_note_page import ResearchNotePage

    mode = note_update["mode"]
    content = note_update["content"]
    title = note_update.get("title")
    page_id_str = note_update.get("page_id")
    reason = note_update.get("reason", "")

    if mode == "create_page":
        r = await db.execute(
            select(_func.max(ResearchNotePage.sort_order))
            .where(ResearchNotePage.project_id == project_id)
        )
        max_order = r.scalar() or 0
        page = ResearchNotePage(
            project_id=project_id,
            title=((title or "AI 新建页").strip() or "AI 新建页")[:200],
            body_md=content[:200_000],
            sort_order=max_order + 1,
            updated_by="ai",
        )
        db.add(page)
        await db.flush()
        return {
            "mode": "create_page",
            "page_id": str(page.id),
            "title": page.title,
            "reason": reason,
            "prev_len": 0,
            "new_len": len(page.body_md),
            "preview": content[:200],
        }

    if mode in ("update_page", "append_to_page"):
        if not page_id_str:
            return None
        try:
            pid = uuid.UUID(page_id_str)
        except ValueError:
            return None
        r = await db.execute(
            select(ResearchNotePage).where(
                ResearchNotePage.id == pid,
                ResearchNotePage.project_id == project_id,
            )
        )
        page = r.scalar_one_or_none()
        if not page:
            return None
        prev_len = len(page.body_md or "")
        if mode == "update_page":
            page.body_md = content[:200_000]
            if title:
                page.title = title.strip()[:200] or page.title
        else:  # append_to_page
            sep = "\n\n" if (page.body_md or "").strip() else ""
            page.body_md = ((page.body_md or "") + sep + content)[:200_000]
        page.updated_at = datetime.now(timezone.utc)
        page.updated_by = "ai"
        await db.flush()
        return {
            "mode": mode,
            "page_id": str(page.id),
            "title": page.title,
            "reason": reason,
            "prev_len": prev_len,
            "new_len": len(page.body_md),
            "preview": content[:200],
        }

    return None


# ──────────── Resume endpoint + finalize helper ────────────


def _clear_pending_plan(session: ConversationSession) -> None:
    state_data = dict(session.state_data or {})
    collab = dict(state_data.get("collaboration") or {})
    if collab.pop("pending_plan", None) is not None:
        state_data["collaboration"] = collab
        session.state_data = state_data
        flag_modified(session, "state_data")


async def _run_probes_for_picks(
    *,
    db: AsyncSession,
    question: str,
    picks: list[dict],
    papers: list[dict],
    fulltext_loader,
    llm_manager,
) -> list[dict]:
    """
    对每个 pick 运行 ProbeAgent，自动查/写 doc.probe_cache。
    - 每篇先查缓存：命中则复用 excerpts 不调 LLM
    - 未命中则跑探针，结果回写 cache

    返回：所有 excerpts 的 dict 列表。
    """
    if not picks or not llm_manager:
        return []
    from app.harness.agents.probe_agent import ProbeAgent
    from app.harness.probe_cache import load_cached_excerpts, save_to_cache

    by_id = {p["id"]: p for p in papers}
    agent = ProbeAgent(llm_manager=llm_manager)

    async def _probe_one(pk: dict) -> tuple[list[dict], bool]:
        """Returns (excerpts, cache_hit)"""
        did = pk.get("doc_id")
        if did not in by_id:
            return [], False
        # 加载 Document ORM 对象（为了读/写 probe_cache）
        doc_res = await db.execute(
            select(Document).where(Document.id == uuid.UUID(did))
        )
        doc = doc_res.scalar_one_or_none()
        if doc is None:
            return [], False

        # ── 查缓存
        cached = load_cached_excerpts(doc, question)
        if cached:
            return cached, True

        # ── 缓存未命中 → 加载全文跑探针
        try:
            ft = await fulltext_loader(did)
        except Exception as e:
            logger.warning("[collab] probe fulltext load failed %s: %s", did, e)
            return [], False
        if not ft:
            return [], False
        try:
            hits = await agent.probe_document(
                question=question, doc_id=did, full_text=ft,
            )
        except Exception as e:
            logger.warning("[collab] probe_document failed %s: %s", did, e)
            return [], False
        excerpts = [h.to_dict() for h in hits]
        # ── 写回缓存（不立即 commit；外层 _finalize_answer 会 commit）
        if excerpts:
            try:
                await save_to_cache(
                    db, doc, question, excerpts,
                    source="collaboration", adopted=False, commit=False,
                )
            except Exception as e:
                logger.warning("[collab] probe cache save failed %s: %s", did, e)
        return excerpts, False

    results = await asyncio.gather(
        *[_probe_one(pk) for pk in picks],
        return_exceptions=True,
    )
    all_excerpts: list[dict] = []
    cache_hit_count = 0
    for r in results:
        if isinstance(r, Exception):
            logger.warning("[collab] probe gather exception: %s", r)
            continue
        excerpts, was_hit = r
        if was_hit:
            cache_hit_count += 1
        all_excerpts.extend(excerpts)
    logger.info(
        "[collab] probes collected %d excerpts | cache_hits=%d/%d picks",
        len(all_excerpts), cache_hit_count, len(picks),
    )
    return all_excerpts


async def _finalize_answer(
    *,
    db: AsyncSession,
    session: ConversationSession,
    proj: Optional[Project],
    question: str,
    papers: list[dict],
    picks: list[dict],
    queries: list[dict],
    fulltext_loader,
    user_memory: str,
    history: list[dict],
    agent,
    probe_excerpts: Optional[list[dict]] = None,
) -> dict:
    """
    Stage 2: 装 excerpts/全文 + 查 KG 子图 + 调 agent.respond + 消费 note_update + 注入 answer rich。
    Question(auto) 和 resume 共用。

    probe_excerpts（新）：探针阶段抽出的原文节选，格式见 _run_probes_for_picks。
      - 非空 → 塞到 papers[i]["excerpts"]，LLM 按节选回答；不再走 full_text[:8000]
      - None/空 → 退化旧路径 full_text[:8000]（仅用于 LLM 不可用 / 用户显式跳过 / 没有全文）
    """
    by_id = {p["id"]: p for p in papers}
    fulltext_picks_out: list[dict] = []

    # —— 模式 A：探针 excerpts 已就绪（新路径）——
    if probe_excerpts:
        excerpts_by_doc: dict[str, list[dict]] = {}
        for ex in probe_excerpts:
            did = ex.get("doc_id")
            if not did:
                continue
            excerpts_by_doc.setdefault(did, []).append(ex)
        # 每篇的 excerpts 按相关性降序
        for did, lst in excerpts_by_doc.items():
            lst.sort(key=lambda e: float(e.get("relevance") or 0), reverse=True)
            target = by_id.get(did)
            if target is not None:
                target["excerpts"] = lst

        # 用户保留了这些 excerpts 到 Stage 2 → 视为"采纳"，写入 cache 供 .md 使用
        from app.harness.probe_cache import mark_entry_adopted
        for did in excerpts_by_doc.keys():
            try:
                doc_res = await db.execute(
                    select(Document).where(Document.id == uuid.UUID(did))
                )
                cache_doc = doc_res.scalar_one_or_none()
                if cache_doc:
                    mark_entry_adopted(cache_doc, question[:300])
            except Exception as e:
                logger.debug("[collab] mark_adopted skipped for %s: %s", did, e)

        # 兼容老前端：把带 excerpts 的篇也塞进 fulltext_picks_out
        for pk in picks:
            did = pk.get("doc_id")
            target = by_id.get(did)
            if not target:
                continue
            if did in excerpts_by_doc:
                fulltext_picks_out.append({
                    "doc_id": did,
                    "title": target.get("title", ""),
                    "reason": pk.get("reason", ""),
                    "excerpt_count": len(excerpts_by_doc[did]),
                })
    else:
        # —— 模式 B：老路径兜底，加载 full_text[:8000] ——
        for pk in picks:
            did = pk.get("doc_id")
            target = by_id.get(did)
            if not target:
                continue
            try:
                ft = await fulltext_loader(did)
            except Exception as e:
                logger.warning("[collab] fetch fulltext failed %s: %s", did, e)
                ft = None
            if ft:
                target["full_text"] = ft[:8000]
                fulltext_picks_out.append({
                    "doc_id": did,
                    "title": target.get("title", ""),
                    "reason": pk.get("reason", ""),
                })

    from app.harness.knowledge_graph.query import build_subgraph_for_queries
    try:
        kg_subgraph = build_subgraph_for_queries(str(session.project_id), queries)
    except Exception as e:
        logger.warning("[collab] kg subgraph build failed: %s", e)
        kg_subgraph = {"entities": [], "missed": []}

    kg_used = [
        {
            "entity": q.get("entity", ""),
            "node_type": q.get("node_type"),
            "reason": q.get("reason", ""),
        }
        for q in queries
    ]

    # 加载项目笔记本所有 page，作为上下文给 LLM（让它决定 create/update/append 哪页）
    from app.models.research_note_page import ResearchNotePage as _RNP
    pg_res = await db.execute(
        select(_RNP)
        .where(_RNP.project_id == session.project_id)
        .order_by(_RNP.sort_order, _RNP.created_at)
    )
    pages_for_prompt = [
        {"id": str(p.id), "title": p.title, "body_md": p.body_md}
        for p in pg_res.scalars().all()
    ]

    result = await agent.respond(
        question=question,
        papers=papers,
        project_description=(proj.description if proj else ""),
        user_memory=user_memory,
        conversation_history=history,
        pages=pages_for_prompt,
        kg_subgraph=kg_subgraph,
    )

    if not result:
        fallback = "抱歉，AI 暂时无法生成回答。请稍后再试，或换一种提问方式。"
        await inject_rich_message(
            db,
            session_id=session.id,
            rich_type="collaboration_answer",
            content=fallback,
            rich_data={
                "answer": fallback,
                "citations": [],
                "follow_up_suggestions": [],
                "confidence": 0.0,
            },
            commit=False,
        )
        _clear_pending_plan(session)
        await db.commit()
        return {"ok": False, "message": fallback}

    applied_note_update = None
    note_update = result.get("note_update")
    if note_update and proj:
        try:
            applied_note_update = await _apply_note_update_to_notebook(
                db, session.project_id, note_update,
            )
        except Exception as e:
            logger.warning("[collab] note_update apply failed: %s", e)
            applied_note_update = None

    # —— 卡片更新建议（LLM 读完全文/探针发现现有卡片错漏时给）——
    card_updates_raw = result.get("card_updates") or []
    card_update_suggestions: list[dict] = []
    if card_updates_raw and proj:
        paper_title_by_id = {p["id"]: p.get("title", "") for p in papers}
        # 只保留本次对话看过的 doc_id（防 LLM 编造 UUID）
        valid_doc_ids = set(paper_title_by_id.keys())
        for cu in card_updates_raw:
            did = cu.get("doc_id")
            if did not in valid_doc_ids:
                continue
            # 取当前 effective 值作为对比基线
            doc_row = next((p for p in papers if p["id"] == did), None)
            field = cu["field"]
            current_value = None
            if doc_row:
                current_value = {
                    "one_line_summary": doc_row.get("one_line_summary"),
                    "ai_summary": doc_row.get("ai_summary"),
                    "ai_key_points": doc_row.get("ai_key_points"),
                }.get(field)
            card_update_suggestions.append({
                "doc_id": did,
                "title": paper_title_by_id.get(did, ""),
                "field": field,
                "new_value": cu["new_value"],
                "reason": cu["reason"],
                "current_value": current_value,
            })

    # 回填 citation.title —— LLM 输出里可能是 UUID / "doc:UUID" / 纯数字索引
    paper_title_by_id = {p["id"]: p.get("title", "") for p in papers}
    citations_enriched: list[dict] = []
    for c in result.get("citations", []) or []:
        if not isinstance(c, dict):
            continue
        cc = dict(c)
        did_raw = cc.get("doc_id") or cc.get("id") or ""
        did = str(did_raw).strip()
        if did.startswith("doc:"):
            did = did[4:]
        title = None
        if did and did in paper_title_by_id:
            title = paper_title_by_id[did]
        elif did.isdigit():
            idx = int(did) - 1
            if 0 <= idx < len(papers):
                title = papers[idx].get("title", "")
        elif isinstance(cc.get("index"), int):
            idx = int(cc["index"]) - 1
            if 0 <= idx < len(papers):
                title = papers[idx].get("title", "")
        if title and not cc.get("title"):
            cc["title"] = title
        # 规范化 doc_id（去前缀），方便前端做锚点
        if did:
            cc["doc_id"] = did
        citations_enriched.append(cc)

    rich_data = {
        "answer": result["answer"],
        "citations": citations_enriched,
        "follow_up_suggestions": result.get("follow_up_suggestions", []),
        "confidence": result.get("confidence", 0.5),
    }
    if applied_note_update:
        rich_data["note_update"] = applied_note_update
    if fulltext_picks_out:
        rich_data["fulltext_picks"] = fulltext_picks_out
    if kg_used:
        rich_data["kg_used"] = kg_used
    if probe_excerpts:
        # 答案气泡可以显示"本回答基于这些探针原文"，方便用户核对
        rich_data["probes_used"] = [
            {
                "doc_id": ex.get("doc_id"),
                "section_label": ex.get("section_label"),
                "section_idx": ex.get("section_idx"),
                "char_start": ex.get("char_start"),
                "char_end": ex.get("char_end"),
                "relevance": ex.get("relevance"),
                "excerpt_quote": ex.get("excerpt_quote"),
            }
            for ex in probe_excerpts
        ]

    await inject_rich_message(
        db,
        session_id=session.id,
        rich_type="collaboration_answer",
        content=result["answer"][:300],
        rich_data=rich_data,
        commit=False,
    )

    # 卡片更新建议：每个建议一个气泡（防多条挤压）
    for cu in card_update_suggestions:
        await inject_rich_message(
            db,
            session_id=session.id,
            rich_type="card_update_suggestion",
            content=f"AI 建议更新「{cu['title'][:40]}」的{cu['field']}",
            rich_data=cu,
            commit=False,
        )

    _clear_pending_plan(session)
    await db.commit()

    return {
        "ok": True,
        "answer": result["answer"],
        "citations": result.get("citations", []),
        "note_update": applied_note_update,
        "fulltext_picks": fulltext_picks_out,
        "kg_used": kg_used,
        "card_update_suggestions": card_update_suggestions,
    }


@router.post("/{session_id}/collaboration/resume")
async def resume_plan(
    session_id: uuid.UUID,
    req: ResumePlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    用户在 ReadPlanBubble 里确认 / 修改 picks + kg_queries 后调用。
    auto_from_now=True → 本 session 剩余时间全部直通 Stage 2，直到退出协作。
    """
    session = await _get_session_or_404(session_id, current_user.id, db)
    collab = await _require_active_collaboration(session)
    pending = collab.get("pending_plan")
    if not pending:
        raise HTTPException(status_code=400, detail="没有待确认的调研计划")

    question = pending.get("question") or ""
    if not question:
        raise HTTPException(status_code=400, detail="待确认计划缺失问题")

    # 切 auto_mode（先写，确保即使后续失败也生效 —— 因为用户明确按了按钮）
    if req.auto_from_now:
        state_data = dict(session.state_data or {})
        col = dict(state_data.get("collaboration") or {})
        col["auto_mode"] = True
        state_data["collaboration"] = col
        session.state_data = state_data
        flag_modified(session, "state_data")

    # 重新 load docs / papers（用户可能在 bubble 里改了 doc 列表，但协作的 doc_ids 在 collab 里不变）
    doc_ids = [uuid.UUID(d) for d in collab.get("doc_ids", [])]
    docs = await _load_docs_with_bucket(db, session.project_id, current_user.id, doc_ids)
    papers: list[dict] = []
    for doc in docs[:30]:
        papers.append({
            "id": doc["id"],
            "title": doc["title"],
            "authors": doc.get("authors"),
            "abstract": doc.get("abstract", ""),
            "one_line_summary": doc.get("one_line_summary"),
            "ai_key_points": doc.get("ai_key_points"),
            "ai_summary": doc.get("ai_summary"),
            "has_fulltext": bool(doc.get("has_fulltext")),
        })

    async def _fulltext_loader(doc_id_str: str) -> Optional[str]:
        try:
            did = uuid.UUID(doc_id_str)
        except Exception:
            return None
        r = await db.execute(
            select(Document.fulltext_text).where(Document.id == did)
        )
        return r.scalar_one_or_none()

    # 严格过滤用户确认的 picks / queries
    valid_ft_ids = {p["id"] for p in papers if p.get("has_fulltext")}
    picks_in: list[dict] = []
    for pk in req.picks or []:
        if not isinstance(pk, dict):
            continue
        did = pk.get("doc_id")
        if not isinstance(did, str) or did not in valid_ft_ids:
            continue
        picks_in.append({
            "doc_id": did,
            "reason": str(pk.get("reason") or "")[:300],
        })

    queries_in: list[dict] = []
    for q in req.kg_queries or []:
        if not isinstance(q, dict):
            continue
        ent = (q.get("entity") or "").strip()
        if not ent:
            continue
        queries_in.append({
            "entity": ent[:200],
            "entity_id": q.get("entity_id"),
            "node_type": q.get("node_type"),
            "reason": str(q.get("reason") or "")[:300],
        })

    # —— 过滤探针 excerpts：用户在 ReadPlanBubble 里勾选了哪些 ——
    stored_probes: list[dict] = list(pending.get("probes") or [])
    # 只保留与最终 picks 对应的 excerpt（用户可能删了某篇 pick）
    pick_doc_ids = {pk["doc_id"] for pk in picks_in}
    stored_probes = [
        ex for ex in stored_probes if ex.get("doc_id") in pick_doc_ids
    ]

    selected_excerpts: Optional[list[dict]] = None
    if req.selected_excerpt_keys is None:
        # 老前端 / 用户没改 → 默认全选 pending_plan 里的所有 excerpts
        selected_excerpts = stored_probes
    elif len(req.selected_excerpt_keys) == 0:
        # 显式空数组 = 用户一个都不要，退化旧路径 full_text[:8000]
        selected_excerpts = None
    else:
        key_set = set(req.selected_excerpt_keys)
        selected_excerpts = [
            ex for ex in stored_probes
            if f"{ex.get('doc_id')}:{ex.get('section_idx')}" in key_set
        ]
        if not selected_excerpts:
            # 传了 keys 但一个都没匹配到 → 也退化（防错选空）
            selected_excerpts = None
    logger.info(
        "[collab.resume] picks=%d queries=%d excerpts_in=%d kept=%d",
        len(picks_in), len(queries_in), len(stored_probes),
        len(selected_excerpts) if selected_excerpts is not None else 0,
    )

    # agent + 上下文
    from app.harness.agents.research_agent import ResearchAgent
    from app.services.core.llm_config_store import get_llm_manager
    manager = await get_llm_manager()
    agent = ResearchAgent(llm_manager=manager)

    proj_res = await db.execute(select(Project).where(Project.id == session.project_id))
    proj = proj_res.scalar_one_or_none()

    user_memory = ""
    try:
        from app.models.user_profile import UserProfile
        pr = await db.execute(
            select(UserProfile).where(
                UserProfile.user_id == current_user.id,
                UserProfile.project_id == session.project_id,
            )
        )
        profile = pr.scalar_one_or_none()
        if profile and profile.memory_text:
            user_memory = profile.memory_text[:1500]
    except Exception:
        pass

    msgs = list(session.messages or [])
    history = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in msgs[-10:]
        if not m.get("rich_type")
    ]

    return await _finalize_answer(
        db=db, session=session, proj=proj, question=question,
        papers=papers, picks=picks_in, queries=queries_in,
        fulltext_loader=_fulltext_loader,
        user_memory=user_memory, history=history, agent=agent,
        probe_excerpts=selected_excerpts,
    )
