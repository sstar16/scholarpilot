"""
Conversation API — 对话驱动的项目创建与检索流程。

核心端点：
- POST /start — 创建对话 session
- POST /{session_id}/message — 发送自然语言，触发 IntentAgent
- POST /{session_id}/confirm — 确认/取消/补充 Agent 决策
- GET /{session_id} — 获取 session 状态（页面刷新恢复）
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.conversation_session import ConversationSession
from app.harness.confirmation import (
    ConfirmationEnvelope,
    build_intent_envelope,
    build_search_mode_envelope,
    check_auto_confirm,
    set_auto_confirm,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversation", tags=["conversation"])


# ──────────── Schemas ────────────

class StartRequest(BaseModel):
    project_id: Optional[uuid.UUID] = None  # 可选：关联已有项目

class MessageRequest(BaseModel):
    content: str

class ConfirmRequest(BaseModel):
    confirmation_id: str
    action: str                    # confirm | supplement | cancel | auto_confirm
    supplement_text: Optional[str] = None
    edits: Optional[dict] = None   # 用户对 Agent 方案的 inline 修改
    search_mode: Optional[str] = None  # 仅 search_mode 确认时使用

class SessionOut(BaseModel):
    id: uuid.UUID
    current_state: str
    state_data: Optional[dict] = None
    messages: Optional[list] = None
    search_mode: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    is_active: bool
    created_at: datetime
    class Config:
        from_attributes = True

class MessageOut(BaseModel):
    role: str           # assistant | system
    content: str
    confirmation: Optional[dict] = None  # ConfirmationEnvelope.to_dict() if any
    state: str          # 当前状态


# ──────────── Helpers ────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _append_message(
    session: ConversationSession,
    role: str,
    content: str,
    metadata: dict = None,
    *,
    rich_type: str = None,
    rich_data: dict = None,
):
    """向 session.messages 追加消息（支持富消息）。"""
    msgs = list(session.messages or [])
    entry = {
        "role": role,
        "content": content,
        "timestamp": _now_iso(),
        "metadata": metadata or {},
    }
    if rich_type:
        entry["rich_type"] = rich_type
        entry["rich_data"] = rich_data or {}
    msgs.append(entry)
    session.messages = msgs
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(session, "messages")


async def _get_session_or_404(
    session_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> ConversationSession:
    result = await db.execute(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="对话 session 不存在")
    return session


async def _run_intent_analysis(
    user_input: str,
    supplement: str = "",
    session_id: Optional[str] = None,
) -> Optional[dict]:
    """
    一次 LLM 调用同时完成"意图解析 + 首轮查询方案"（ResearchDecisionAgent）。
    失败时降级到只出意图的 IntentAnalysisAgent，保持签名向后兼容。
    返回 dict 扁平结构：意图字段 + 可选 query_plan 子字段。

    当 session_id 提供时，用 async_llm_context 包装 LLM 调用并发送 phase
    事件到 workbench SSE 通道，供前端实时展示进度。
    """
    from app.services.core.llm_config_store import get_llm_manager
    from app.services.core.llm_context import async_llm_context, emit_phase
    from app.harness.agents.research_decision_agent import ResearchDecisionAgent
    from app.harness.agents.intent_agent import IntentAnalysisAgent

    manager = await get_llm_manager()

    async with async_llm_context(
        session_id=session_id,
        agent_name="ResearchDecisionAgent",
    ):
        await emit_phase("analyzing_intent", "理解用户意图")
        decision_agent = ResearchDecisionAgent(llm_manager=manager)
        result = await decision_agent.decide(
            user_input=user_input, supplementary_context=supplement,
        )
        if result is not None:
            await emit_phase("intent_ready", "已生成初步计划")
            return result

    # 降级：只出意图的旧版 Agent
    async with async_llm_context(
        session_id=session_id,
        agent_name="IntentAnalysisAgent",
    ):
        await emit_phase("analyzing_intent_fallback", "降级到基础意图分析")
        fallback = IntentAnalysisAgent(llm_manager=manager)
        result = await fallback.analyze(
            user_input=user_input, supplementary_context=supplement,
        )
        if result is not None:
            await emit_phase("intent_ready", "意图已解析")
        return result


async def _create_project_from_intent(
    intent: dict, user_id: uuid.UUID, session: ConversationSession, db: AsyncSession
) -> Project:
    """从 intent 结果创建项目。"""
    from app.services.core.llm_context import async_llm_context, emit_phase

    async with async_llm_context(
        session_id=str(session.id),
        agent_name="ProjectBuilder",
    ):
        await emit_phase("creating_project", "创建项目中")

    domains = intent.get("domains", ["interdisciplinary"])
    year_focus = intent.get("year_focus", "recent")

    # 根据 year_focus 调整 search_config
    from app.schemas.project import DEFAULT_SEARCH_CONFIG
    search_config = dict(DEFAULT_SEARCH_CONFIG)

    # 根据 doc_types 调整 preferred_sources
    doc_types = intent.get("doc_types", "literature")
    if doc_types == "patent":
        search_config["preferred_doc_type"] = "patent"
    elif doc_types == "both":
        search_config["preferred_doc_type"] = "both"

    if intent.get("suggested_sources"):
        search_config["preferred_sources"] = intent["suggested_sources"]

    # ResearchDecisionAgent 可能已预生成首轮查询方案 → 持久化供 prepare_round 复用
    precomputed_plan = intent.get("query_plan")
    if isinstance(precomputed_plan, dict):
        search_config["precomputed_plan"] = precomputed_plan

    project = Project(
        user_id=user_id,
        title=intent["title"],
        description=intent["description"],
        domain=domains[0],
        domains=domains,
        search_config=search_config,
    )
    db.add(project)
    await db.flush()

    # 关联 session
    session.project_id = project.id

    # Fire PROJECT_CREATE hook
    from app.harness.hook_engine import HookEngine, HookPoint
    hook = HookEngine.get_instance()
    await hook.fire(HookPoint.PROJECT_CREATE, {
        "project_id": str(project.id),
        "user_id": str(user_id),
        "intent": intent,
    })

    return project


# ──────────── Endpoints ────────────

@router.post("/start", response_model=SessionOut, status_code=201)
async def start_conversation(
    req: StartRequest = StartRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新的对话 session。"""
    session = ConversationSession(
        user_id=current_user.id,
        project_id=req.project_id,
        current_state="idle",
        state_data={},
        messages=[],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Fire hook
    from app.harness.hook_engine import HookEngine, HookPoint
    hook = HookEngine.get_instance()
    await hook.fire(HookPoint.CONVERSATION_START, {
        "session_id": str(session.id),
        "user_id": str(current_user.id),
    })

    return session


@router.get("/by-project/{project_id}")
async def get_session_by_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取项目关联的活跃 session（用于 ProjectView 恢复对话）。"""
    result = await db.execute(
        select(ConversationSession).where(
            ConversationSession.project_id == project_id,
            ConversationSession.user_id == current_user.id,
            ConversationSession.is_active == True,
        ).order_by(ConversationSession.updated_at.desc()).limit(1)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"session": None}
    return {"session": SessionOut.model_validate(session)}


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取 session 完整状态（页面刷新恢复）。"""
    return await _get_session_or_404(session_id, current_user.id, db)


@router.post("/{session_id}/message", response_model=MessageOut)
async def send_message(
    session_id: uuid.UUID,
    req: MessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    发送自然语言消息。
    在 idle 状态下触发 IntentAnalysisAgent。
    """
    session = await _get_session_or_404(session_id, current_user.id, db)

    if not session.is_active:
        raise HTTPException(status_code=400, detail="该对话已结束")

    # 记录用户消息
    _append_message(session, "user", req.content)

    state = session.current_state

    # ── idle → intent_analysis ──
    if state == "idle":
        session.current_state = "intent_analysis"
        await db.commit()

        intent_result = await _run_intent_analysis(
            req.content, session_id=str(session.id)
        )

        if intent_result is None:
            session.current_state = "idle"
            msg = "呜喵…脑子一时短路了，AI 分析暂时宕机。右上角有「手动表单」可以先顶上~"
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(role="assistant", content=msg, state="idle")

        # 非研究请求（问候/闲聊/占位符等）：不创建项目，保持 idle 并引导用户
        if intent_result.get("is_research_request") is False:
            session.current_state = "idle"
            msg = intent_result.get("reply") or "喵？没太看懂，扔个研究方向过来试试~"
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(role="assistant", content=msg, state="idle")

        # 构建确认信封
        envelope = build_intent_envelope(intent_result)
        state_data = dict(session.state_data or {})
        state_data["pending_envelope"] = envelope.to_dict()
        state_data["raw_intent"] = intent_result
        state_data["original_input"] = req.content
        state_data["supplement_history"] = ""
        session.state_data = state_data
        session.current_state = "intent_confirmation"

        # Confirmation envelope 必须通过 API 返回（前端依赖 data.content + data.confirmation
        # 同时渲染确认气泡和按钮），因此这里仍用 _append_message + 返回 content
        _append_message(session, "assistant", envelope.summary_zh, {"type": "confirmation", "envelope_id": envelope.confirmation_id})

        await db.commit()
        return MessageOut(
            role="assistant",
            content=envelope.summary_zh,
            confirmation=envelope.to_dict(),
            state="intent_confirmation",
        )

    # ── intent_confirmation + supplement (用户补充) ──
    if state == "intent_confirmation":
        # 用户在确认阶段输入了更多文本 → 当作 supplement
        state_data = dict(session.state_data or {})
        original_input = state_data.get("original_input", "")
        prev_supplement = state_data.get("supplement_history", "")
        new_supplement = f"{prev_supplement}\n{req.content}".strip()

        intent_result = await _run_intent_analysis(
            original_input, new_supplement, session_id=str(session.id)
        )

        if intent_result is None:
            msg = "呜喵…补充的这段我没吃透。要么直接点确认，要么在卡片里手动改~"
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(role="assistant", content=msg, state="intent_confirmation")

        # 非研究请求：保留原 pending envelope，仅附加引导语，用户可继续补充/取消
        if intent_result.get("is_research_request") is False:
            msg = intent_result.get("reply") or "喵~这句还不够具体，再往研究方向上靠一点？"
            state_data["supplement_history"] = new_supplement
            session.state_data = state_data
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(
                role="assistant",
                content=msg,
                confirmation=state_data.get("pending_envelope"),
                state="intent_confirmation",
            )

        envelope = build_intent_envelope(intent_result)
        state_data["pending_envelope"] = envelope.to_dict()
        state_data["raw_intent"] = intent_result
        state_data["supplement_history"] = new_supplement
        session.state_data = state_data

        _append_message(session, "assistant", envelope.summary_zh, {"type": "confirmation", "envelope_id": envelope.confirmation_id})

        await db.commit()
        return MessageOut(
            role="assistant",
            content=envelope.summary_zh,
            confirmation=envelope.to_dict(),
            state="intent_confirmation",
        )

    # ── collaboration_active: route every message to research_agent via collaboration ──
    if state == "collaboration_active":
        return await _handle_collaboration_message(session, req.content, current_user, db)

    # ── collaboration_selecting: user is picking docs, don't auto-respond ──
    if state == "collaboration_selecting":
        msg = "喵~现在在挑文献呢，先在上面气泡里勾好，或者打个「取消」放我出去。"
        if "取消" in req.content or "退出" in req.content:
            session.current_state = "idle"
            msg = "好嘞，爪子一缩，退出协作选择~"
        _append_message(session, "system", msg)
        await db.commit()
        return MessageOut(role="system", content=msg, state=session.current_state)

    # ── project-linked session: Intent Router ──
    if session.project_id and state in ("classification", "keyword_confirmation", "investigation", "round_finalize", "idle"):
        return await _handle_project_message(session, req.content, current_user, db)

    # 其他状态下的消息暂不处理：模式互斥兜底
    msg = f"喵喵喵！现在正陷在「{state}」这个流程里呢，要切别的模式得先走完或者点「退出」把我放出来呀~"
    _append_message(session, "system", msg)
    await db.commit()
    return MessageOut(role="system", content=msg, state=state)


async def _handle_collaboration_message(
    session: ConversationSession,
    content: str,
    current_user,
    db: AsyncSession,
) -> MessageOut:
    """
    协作模式内的消息：检查退出意图 → 否则路由到 research_agent。
    禁止任何检索/上传操作。
    """
    # 快速关键词判断退出意图（不走完整 LLM 分类以节省延迟）
    lower = content.strip().lower()
    if any(kw in content for kw in ("退出协作", "结束协作", "离开协作", "退出")) and len(content) < 20:
        msg = "想走啦？喵~ 顶栏上有「退出协作」按钮，点一下就能选归档还是保留~"
        _append_message(session, "assistant", msg)
        await db.commit()
        return MessageOut(role="assistant", content=msg, state="collaboration_active")

    # 检测检索相关请求并拒绝
    search_keywords = ("检索", "开始新一轮", "新一轮", "搜索文献", "再找一轮")
    if any(kw in content for kw in search_keywords):
        msg = "喵喵！协作模式开着呢，不能同时开检索哦~ 先点「退出协作」放我出去，再来找新论文嘛。"
        _append_message(session, "assistant", msg)
        await db.commit()
        return MessageOut(role="assistant", content=msg, state="collaboration_active")

    # 自由提问 — 复用 collaboration question 逻辑
    from app.api.collaboration import collaboration_question, QuestionRequest
    from app.services.core.llm_context import async_llm_context, emit_phase
    try:
        async with async_llm_context(
            session_id=str(session.id),
            agent_name="ResearchAgent",
        ):
            await emit_phase("answering_collab_question", "回答协作问题")
            await collaboration_question(
                session_id=session.id,
                req=QuestionRequest(question=content),
                current_user=current_user,
                db=db,
            )
            await emit_phase("collab_answer_ready", "协作回答已生成")
        # Rich message has been injected by collaboration_question; return latest
        await db.refresh(session)
        # content="" — 答案已通过 rich message + SSE 送达
        return MessageOut(
            role="assistant",
            content="",
            state="collaboration_active",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[collab] question failed: %s", e)
        msg = "抱歉，协作回答暂时不可用，请稍后再试。"
        _append_message(session, "assistant", msg)
        await db.commit()
        return MessageOut(role="assistant", content=msg, state="collaboration_active")


@router.post("/{session_id}/confirm", response_model=MessageOut)
async def confirm_decision(
    session_id: uuid.UUID,
    req: ConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    确认/取消/补充 Agent 决策。
    """
    session = await _get_session_or_404(session_id, current_user.id, db)
    state = session.current_state
    state_data = dict(session.state_data or {})

    # ── cancel ──
    if req.action == "cancel":
        session.current_state = "idle"
        state_data.pop("pending_envelope", None)
        state_data.pop("raw_intent", None)
        session.state_data = state_data
        msg = "已取消，请重新描述您的研究需求。"
        _append_message(session, "system", msg)
        await db.commit()
        return MessageOut(role="system", content=msg, state="idle")

    # ── supplement (在 intent_confirmation 阶段) ──
    if req.action == "supplement" and state == "intent_confirmation":
        if not req.supplement_text:
            raise HTTPException(status_code=400, detail="补充内容不能为空")

        original_input = state_data.get("original_input", "")
        prev_supplement = state_data.get("supplement_history", "")
        new_supplement = f"{prev_supplement}\n{req.supplement_text}".strip()

        intent_result = await _run_intent_analysis(
            original_input, new_supplement, session_id=str(session.id)
        )
        if intent_result is None:
            msg = "补充分析失败，请直接确认当前方案。"
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(role="assistant", content=msg, state="intent_confirmation")

        # 非研究请求：保留原 pending envelope，仅附加引导语
        if intent_result.get("is_research_request") is False:
            msg = intent_result.get("reply") or "补充内容仍不够明确，请继续描述研究方向。"
            state_data["supplement_history"] = new_supplement
            session.state_data = state_data
            _append_message(session, "user", req.supplement_text, {"type": "supplement"})
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(
                role="assistant",
                content=msg,
                confirmation=state_data.get("pending_envelope"),
                state="intent_confirmation",
            )

        envelope = build_intent_envelope(intent_result)
        state_data["pending_envelope"] = envelope.to_dict()
        state_data["raw_intent"] = intent_result
        state_data["supplement_history"] = new_supplement
        session.state_data = state_data

        _append_message(session, "user", req.supplement_text, {"type": "supplement"})
        _append_message(session, "assistant", envelope.summary_zh, {"type": "confirmation"})

        await db.commit()
        return MessageOut(
            role="assistant",
            content=envelope.summary_zh,
            confirmation=envelope.to_dict(),
            state="intent_confirmation",
        )

    # ── auto_confirm ──
    if req.action == "auto_confirm":
        pending = state_data.get("pending_envelope", {})
        action_type = pending.get("action_type", "")
        state_data = set_auto_confirm(state_data, action_type)
        session.state_data = state_data
        # 然后执行 confirm 逻辑
        req.action = "confirm"

    # ── confirm — intent_confirmation ──
    if req.action == "confirm" and state == "intent_confirmation":
        intent = state_data.get("raw_intent", {})
        if not intent:
            raise HTTPException(status_code=400, detail="无待确认的意图分析结果")

        # 应用用户的 inline edits
        if req.edits:
            for key, value in req.edits.items():
                if key in intent and value is not None:
                    intent[key] = value

        # 创建项目
        project = await _create_project_from_intent(intent, current_user.id, session, db)

        # 清理 state_data，进入 search_mode_selection
        session.state_data = {
            "auto_confirm": state_data.get("auto_confirm", {}),
            "intent": intent,
        }
        session.current_state = "search_mode_selection"

        # 构建检索模式选择信封
        mode_envelope = build_search_mode_envelope()

        state_data_new = dict(session.state_data)
        state_data_new["pending_envelope"] = mode_envelope.to_dict()
        session.state_data = state_data_new

        msg = f"项目「{project.title}」已创建！\n\n{mode_envelope.summary_zh}"
        _append_message(session, "assistant", msg, {"type": "project_created", "project_id": str(project.id)})

        await db.commit()
        return MessageOut(
            role="assistant",
            content=msg,
            confirmation=mode_envelope.to_dict(),
            state="search_mode_selection",
        )

    # ── confirm — search_mode_selection ──
    if req.action in ("confirm", "static_db", "api", "hybrid") and state == "search_mode_selection":
        # 用户选择检索模式
        mode = req.search_mode or req.action
        if mode == "confirm":
            # 通用 confirm 动作未携带明确模式 → 报错让用户点模式卡片
            raise HTTPException(
                status_code=400,
                detail="请选择检索模式（静态知识库 / API / 混合）",
            )
        if mode not in ("static_db", "api", "hybrid"):
            raise HTTPException(status_code=400, detail=f"无效的检索模式: {mode}")

        session.search_mode = mode
        session.current_state = "keyword_confirmation"

        # Persist search_mode to project.search_config so KeywordConfirmPanel picks it up
        if session.project_id:
            from app.models.project import Project as _Proj
            _proj_r = await db.execute(select(_Proj).where(_Proj.id == session.project_id))
            _proj = _proj_r.scalar_one_or_none()
            if _proj:
                cfg = dict(_proj.search_config or {})
                cfg["search_mode"] = mode
                _proj.search_config = cfg

        state_data_new = dict(session.state_data or {})
        state_data_new.pop("pending_envelope", None)
        session.state_data = state_data_new

        mode_names = {"static_db": "静态知识库", "api": "API 实时检索", "hybrid": "混合检索"}
        msg = f"已选择 **{mode_names.get(mode, mode)}** 模式。请前往项目页面开始检索。"
        _append_message(session, "assistant", msg, {"type": "search_mode_selected", "mode": mode})

        # Fire hook
        from app.harness.hook_engine import HookEngine, HookPoint
        hook = HookEngine.get_instance()
        await hook.fire(HookPoint.SEARCH_MODE_SELECTED, {
            "session_id": str(session.id),
            "project_id": str(session.project_id),
            "search_mode": mode,
        })

        await db.commit()
        return MessageOut(role="assistant", content=msg, state="keyword_confirmation")

    raise HTTPException(
        status_code=400,
        detail=f"当前状态 ({state}) 不支持操作 ({req.action})",
    )


async def _handle_project_message(
    session: ConversationSession,
    content: str,
    current_user,
    db: AsyncSession,
) -> MessageOut:
    """
    Handle messages in project-linked sessions via LLM Intent Router.
    Routes to: upload, research Q&A, search, or general chat.
    """
    import json as _json
    import re as _re

    # 1. Run Intent Router
    intent_data = await _run_intent_router(content, session_id=str(session.id))
    intent_type = intent_data.get("intent", "general_chat")
    extracted = intent_data.get("extracted", {})

    # 2. Route by intent
    if intent_type in ("upload_doi", "upload_search"):
        # Import flow
        from app.services.document_import import import_by_doi, import_by_natural_language

        doi = extracted.get("doi")
        # Also try regex extraction from original message
        if not doi:
            doi_match = _re.search(r'(10\.\d{4,}/\S+)', content)
            if doi_match:
                doi = doi_match.group(1)

        if doi:
            result = await import_by_doi(
                doi, str(session.project_id), str(current_user.id), "very_relevant", db,
            )
            if result:
                await db.commit()
                msg = f"已导入文献「{result['title']}」到很相关桶。"
                _append_message(session, "assistant", msg, {"type": "upload_result", "document_id": result["document_id"]})
                await db.commit()
                return MessageOut(role="assistant", content=msg, state=session.current_state)

        # Fuzzy search — return candidates as confirmation
        candidates = await import_by_natural_language(
            extracted.get("keywords") or extracted.get("title") or content,
            str(session.project_id), str(current_user.id), "very_relevant", db,
        )
        if candidates:
            from app.harness.confirmation import ConfirmationEnvelope
            candidate_lines = []
            for i, c in enumerate(candidates[:5], 1):
                candidate_lines.append(f"{i}. **{c.get('title', '未知')}**" + (f" (DOI: {c.get('doi', '')})" if c.get('doi') else ""))

            envelope = ConfirmationEnvelope(
                agent_name="document_import",
                action_type="upload_confirm",
                summary_zh="找到以下匹配文献：\n" + "\n".join(candidate_lines),
                details={"candidates": candidates},
                options=["confirm", "cancel"],
                auto_confirmable=False,
            )
            state_data = dict(session.state_data or {})
            state_data["pending_envelope"] = envelope.to_dict()
            state_data["upload_candidates"] = candidates
            session.state_data = state_data

            # Confirmation envelope 必须走 _append_message + API content
            _append_message(session, "assistant", envelope.summary_zh, {"type": "upload_candidates"})
            await db.commit()
            return MessageOut(
                role="assistant", content=envelope.summary_zh,
                confirmation=envelope.to_dict(), state=session.current_state,
            )

        msg = "未找到匹配的文献。请尝试提供 DOI，或使用上传按钮上传 PDF。"
        _append_message(session, "assistant", msg)
        await db.commit()
        return MessageOut(role="assistant", content=msg, state=session.current_state)

    elif intent_type == "analyze_documents":
        # Gate: collaboration requires HAS_LIBRARY scene
        from app.services.feature_gate import check as gate_check
        gate = await gate_check("collaboration", session.project_id, db)
        if not gate.allowed:
            blocked_msg = f"无法进入协作模式：{gate.reason}"
            _append_message(
                session,
                "assistant",
                blocked_msg,
                {
                    "rich_type": "feature_gate_blocked",
                    "feature": "collaboration",
                    "scene": gate.scene,
                    "reason": gate.reason,
                    "suggested_action": gate.suggested_action,
                },
            )
            await db.commit()
            return MessageOut(
                role="assistant",
                content=blocked_msg,
                state=session.current_state,
            )

        # Enter collaboration selection mode — inject collaboration_scope rich message
        from app.api.collaboration import suggest_scope
        try:
            await suggest_scope(
                session_id=session.id,
                current_user=current_user,
                db=db,
            )
            await db.refresh(session)
            msg = "我已为您列出了已分类的文献，请在上方选择本次协作要分析的文献"
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(
                role="assistant",
                content=msg,
                state="collaboration_selecting",
            )
        except HTTPException as he:
            msg = f"无法进入协作模式: {he.detail}"
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(role="assistant", content=msg, state=session.current_state)

    elif intent_type == "exit_collaboration":
        msg = "喵？现在根本没在协作模式里，不用退~"
        _append_message(session, "assistant", msg)
        await db.commit()
        return MessageOut(role="assistant", content=msg, state=session.current_state)

    elif intent_type == "research_qa":
        # Delegate to ResearchAgent
        from app.services.core.llm_config_store import get_llm_manager
        from app.services.core.llm_context import async_llm_context, emit_phase
        from app.harness.agents.research_agent import ResearchAgent
        from app.models.document import Document
        from app.models.document_classification import DocumentClassification

        docs_result = await db.execute(
            select(Document)
            .join(DocumentClassification, DocumentClassification.document_id == Document.id)
            .where(
                DocumentClassification.project_id == session.project_id,
                DocumentClassification.user_id == current_user.id,
                DocumentClassification.bucket == "very_relevant",
            ).limit(20)
        )
        docs = docs_result.scalars().all()
        papers = [{"id": str(d.id), "title": d.title, "authors": d.authors, "abstract": d.abstract,
                    "one_line_summary": d.one_line_summary, "ai_key_points": d.ai_key_points} for d in docs]

        if not papers:
            msg = "很相关桶中暂无文献，请先分类一些文献后再提问。"
            _append_message(session, "assistant", msg)
            await db.commit()
            return MessageOut(role="assistant", content=msg, state=session.current_state)

        manager = await get_llm_manager()
        history = [{"role": m["role"], "content": m["content"]} for m in (session.messages or [])[-10:]]

        from app.models.project import Project as _Proj
        proj_r = await db.execute(select(_Proj).where(_Proj.id == session.project_id))
        proj = proj_r.scalar_one_or_none()

        async with async_llm_context(
            session_id=str(session.id),
            agent_name="ResearchAgent",
        ):
            await emit_phase("answering_research_qa", "检索相关文献 + 回答研究问题")
            agent = ResearchAgent(llm_manager=manager)
            result = await agent.answer(
                question=content, papers=papers,
                project_description=proj.description if proj else "",
                conversation_history=history,
            )
            if result:
                await emit_phase("research_answer_ready", "研究回答已生成")

        if result:
            msg = result["answer"]
            _append_message(session, "assistant", msg, {"type": "research_answer", "citations": result.get("citations")})
        else:
            msg = "分析暂时不可用，请稍后重试。"
            _append_message(session, "assistant", msg)

        await db.commit()
        return MessageOut(role="assistant", content=msg, state=session.current_state)

    else:
        # general_chat / search_request — simple response
        msg = "收到喵~ 想继续聊就聊，想开新一轮检索就说一声，想协作研究就点上面的「协作模式」，随你挑！"
        _append_message(session, "assistant", msg)
        await db.commit()
        return MessageOut(role="assistant", content=msg, state=session.current_state)


async def _run_intent_router(message: str, session_id: Optional[str] = None) -> dict:
    """Run LLM Intent Router to classify message intent."""
    import json as _json
    import re as _re

    try:
        from app.services.core.llm_config_store import get_llm_manager
        from app.services.core.llm_context import async_llm_context, emit_phase
        from app.harness.prompts.intent_router import build_intent_router_prompt

        manager = await get_llm_manager()
        prompt = build_intent_router_prompt(message)

        async with async_llm_context(
            session_id=session_id,
            agent_name="IntentRouter",
        ):
            await emit_phase("routing_intent", "识别消息意图")
            result = await manager.generate(
                prompt, temperature=0.1,
                response_format={"type": "json_object"},
            )

        if result:
            match = _re.search(r'\{[\s\S]*"intent"[\s\S]*\}', result)
            if match:
                return _json.loads(match.group())
    except Exception as e:
        logger.warning("[IntentRouter] Failed: %s", e)

    return {"intent": "general_chat", "extracted": {}}


