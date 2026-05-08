"""文档分类 API — 4桶系统 + 文献原文管理"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid

from app.database import get_db
from app.dependencies import get_current_user, get_current_user_flexible
from app.models.user import User
from app.models.project import Project
from app.models.document import Document
from app.models.document_classification import DocumentClassification
from app.models.round_document import RoundDocument
from app.schemas.classification import (
    ClassifyRequest,
    MoveRequest,
    ClassificationOut,
    BucketSummary,
    BucketDocumentOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["classification"])


@router.put("/{project_id}/documents/{document_id}/classify", response_model=ClassificationOut)
async def classify_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: ClassifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """将文档分类到桶（upsert）"""
    await _verify_project(project_id, current_user.id, db)

    # 验证文档存在 + 保存对象供后续 source 判断
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc_obj = doc_result.scalar_one_or_none()
    if not doc_obj:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 查找当前轮次（用于 classified_in_round_id）
    round_id = await _get_active_round_id(project_id, db)

    # Upsert
    existing = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id == document_id,
        )
    )
    classification = existing.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if classification:
        old_bucket = classification.bucket
        classification.bucket = req.bucket
        classification.reason = req.reason or classification.reason
        classification.moved_at = now if old_bucket != req.bucket else classification.moved_at
    else:
        classification = DocumentClassification(
            user_id=current_user.id,
            project_id=project_id,
            document_id=document_id,
            bucket=req.bucket,
            classified_in_round_id=round_id,
            reason=req.reason,
            classified_at=now,
        )
        db.add(classification)

    await db.commit()
    await db.refresh(classification)

    logger.info("[Classification] doc=%s → bucket=%s (project=%s)", document_id, req.bucket, project_id)

    # Phase 3.2: Trigger async KG update
    try:
        from app.workers.graph_tasks import update_graph_for_document
        update_graph_for_document.delay(str(project_id), str(document_id), req.bucket)
    except Exception as _e:
        logger.warning("[Classification] KG update dispatch failed: %s", _e)

    # Phase 3.3: Trigger fulltext download for very_relevant
    # 注意：付费 PDF 源（PAID_PDF=True，目前仅 patenthub）每次下载有费用，
    # **不在此自动触发**，只响应用户手动点击 download-fulltext。
    from app.services.fetchers.international import is_paid_pdf_source
    if req.bucket == "very_relevant" and not is_paid_pdf_source(doc_obj.source):
        try:
            from app.workers.fulltext_tasks import download_single
            download_single.delay(str(document_id), str(project_id))
        except Exception as _e:
            logger.warning("[Classification] Fulltext download dispatch failed: %s", _e)

    # 项目食谱：每次反馈后异步 regenerate（< 100ms，纯统计无 LLM）。
    # 食谱写到 user_profiles.auto_recipe_md，下一次 build_combined_memory_for_agents
    # 会自动包含进 agent prompt。
    try:
        from app.workers.recipe_tasks import regenerate_project_recipe_task
        regenerate_project_recipe_task.delay(str(project_id), str(current_user.id))
    except Exception as _e:
        logger.warning("[Classification] Recipe regenerate dispatch failed: %s", _e)

    return classification


@router.put("/{project_id}/documents/{document_id}/move", response_model=ClassificationOut)
async def move_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: MoveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """桶间移动文档"""
    await _verify_project(project_id, current_user.id, db)

    result = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id == document_id,
        )
    )
    classification = result.scalar_one_or_none()
    if not classification:
        raise HTTPException(status_code=404, detail="该文档尚未分类")

    old_bucket = classification.bucket
    classification.bucket = req.to_bucket
    classification.moved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(classification)

    # Phase 3.2: Trigger async KG update on move
    try:
        from app.workers.graph_tasks import update_graph_for_document
        update_graph_for_document.delay(str(project_id), str(document_id), req.to_bucket)
    except Exception as _e:
        logger.warning("[Classification] KG update dispatch failed on move: %s", _e)

    # 项目食谱：移动也算反馈信号变化，重算一次。
    try:
        from app.workers.recipe_tasks import regenerate_project_recipe_task
        regenerate_project_recipe_task.delay(str(project_id), str(current_user.id))
    except Exception as _e:
        logger.warning("[Classification] Recipe regenerate dispatch failed on move: %s", _e)

    return classification


@router.delete("/{project_id}/documents/{document_id}/classify", status_code=204)
async def unclassify_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消分类"""
    await _verify_project(project_id, current_user.id, db)

    result = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id == document_id,
        )
    )
    classification = result.scalar_one_or_none()
    if classification:
        await db.delete(classification)
        await db.commit()


@router.get("/{project_id}/buckets", response_model=BucketSummary)
async def get_buckets(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取项目4个桶的全部内容"""
    await _verify_project(project_id, current_user.id, db)

    result = await db.execute(
        select(DocumentClassification, Document)
        .join(Document, DocumentClassification.document_id == Document.id)
        .where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
        )
        .order_by(DocumentClassification.classified_at.desc())
    )

    buckets = {"very_relevant": [], "relevant": [], "uncertain": [], "irrelevant": []}
    counts = {"very_relevant": 0, "relevant": 0, "uncertain": 0, "irrelevant": 0}

    for cls, doc in result.all():
        # 获取最佳 agent_score（跨轮次取最高分）
        best_score_q = await db.execute(
            select(func.max(RoundDocument.agent_score)).where(
                RoundDocument.document_id == doc.id
            )
        )
        best_score = best_score_q.scalar()

        item = BucketDocumentOut(
            document_id=doc.id,
            title=doc.title or "",
            one_line_summary=doc.effective_one_line_summary,
            source=doc.source,
            agent_score=best_score,
            classified_at=cls.classified_at,
            bucket=cls.bucket,
            fulltext_status=doc.fulltext_status,
            fulltext_pdf_status=doc.fulltext_pdf_status,
            fulltext_pdf_path=doc.fulltext_pdf_path,
            fulltext_html_status=doc.fulltext_html_status,
            fulltext_html_path=doc.fulltext_html_path,
            fulltext_path=doc.fulltext_path,
            pdf_url=doc.pdf_url,
            doi=doc.doi,
            url=doc.url,
            external_id=doc.external_id,
        )
        if cls.bucket in buckets:
            buckets[cls.bucket].append(item)
            counts[cls.bucket] += 1

    return BucketSummary(**buckets, counts=counts)


# ── helpers ──

@router.post("/{project_id}/documents/{document_id}/download-fulltext")
async def download_document_fulltext(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    format: str = "auto",  # auto | pdf | html
    force: bool = False,    # patenthub 超额后用户二次确认：true = 绕过单轮 5 次上限
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """触发单篇文献全文下载。

    format (query param):
      - "auto"  : 先尝试 PDF，失败退 HTML fallback（默认）
      - "pdf"   : 只下 PDF，不做 HTML 兜底
      - "html"  : 只抓 landing page HTML 快照（与现有 PDF 共存）

    PDF 和 HTML 是**独立通道**，可以共存：已有 PDF 的文献可以再补 HTML，反之亦然。
    """
    if format not in ("auto", "pdf", "html"):
        raise HTTPException(status_code=400, detail="format 必须是 auto/pdf/html")

    await _verify_project(project_id, current_user.id, db)

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 未触发 PDF 通道的纯 HTML 下载不受 patenthub 守门影响
    _involves_pdf_channel = format in ("auto", "pdf")

    # 按通道幂等：这个格式已经可用就直接返回
    if format == "pdf" and doc.fulltext_pdf_status == "available":
        return {"status": "already_available", "format": "pdf", "message": "PDF 已下载"}
    if format == "html" and doc.fulltext_html_status == "available":
        return {"status": "already_available", "format": "html", "message": "HTML 已下载"}
    if format == "auto" and "available" in (doc.fulltext_pdf_status, doc.fulltext_html_status):
        return {"status": "already_available", "format": "auto", "message": "全文已下载"}

    # 预检：连 landing_url 也没有时才拒绝
    if not (doc.pdf_url or doc.doi or doc.url):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_source",
                "message": "该文献既无 PDF 也无原文页面链接，请手动上传 PDF 原文",
            },
        )

    # 重置对应通道的脏状态（downloading/failed → not_attempted），让 worker 不会 skip
    from sqlalchemy import update as sa_update
    reset_values: dict = {}
    if format in ("auto", "pdf") and doc.fulltext_pdf_status in ("downloading", "failed"):
        reset_values["fulltext_pdf_status"] = "not_attempted"
    if format in ("auto", "html") and doc.fulltext_html_status in ("downloading", "failed"):
        reset_values["fulltext_html_status"] = "not_attempted"
    if reset_values:
        await db.execute(
            sa_update(Document).where(Document.id == document_id).values(**reset_values)
        )
        await db.commit()

    # PatentHub PDF 预算守门（方案 B + 二次确认）：
    # - 非 patenthub 源 / 非 PDF 通道：直接 queue
    # - patenthub + 涉及 PDF：try_consume，超额返回 HTTP 402 带 budget 信息，前端弹二次确认
    # - 二次确认后前端重发请求带 force=true，绕过上限（仍扣 ¥1）
    patenthub_round_id: str | None = None
    if doc.source == "patenthub" and _involves_pdf_channel:
        from app.services.patenthub_budget import try_consume, resolve_round_id
        resolved = await resolve_round_id(db, document_id, project_id)
        if not resolved:
            raise HTTPException(
                status_code=422,
                detail={"code": "no_round", "message": "无法确定文献所属检索轮次，预算守门失败"},
            )
        ok, used, mx = await try_consume(resolved, force=force)
        if not ok:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "patenthub_budget_exceeded",
                    "message": (
                        f"本轮 PatentHub PDF 已下载 {used}/{mx} 篇"
                        f"（累计约 ¥{used * 1.1:.1f}），是否继续？每篇约 ¥1.1（详情 0.1 + PDF 1.0）"
                    ),
                    "used": used,
                    "max": mx,
                    "cost_per_pdf": 1.1,
                    "round_id": resolved,
                },
            )
        patenthub_round_id = resolved

    try:
        from app.workers.fulltext_tasks import download_single
        download_single.delay(
            str(document_id), str(project_id), format,
            patenthub_round_id=patenthub_round_id,
        )
    except Exception as e:
        # 提交失败需回退已预扣的预算
        if patenthub_round_id:
            try:
                from app.services.patenthub_budget import refund
                await refund(patenthub_round_id)
            except Exception:
                pass
        raise HTTPException(status_code=503, detail=f"任务提交失败: {e}")

    return {
        "status": "queued",
        "format": format,
        "message": "全文下载任务已提交",
        "patenthub_round_id": patenthub_round_id,
    }


@router.get("/{project_id}/rounds/{round_id}/patenthub-budget")
async def get_patenthub_budget(
    project_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    读单轮 PatentHub PDF 下载预算状态（前端展示"本轮剩余 N/5 次"用）。

    返回 {round_id, used, max, remaining, exhausted}。
    """
    await _verify_project(project_id, current_user.id, db)
    from app.services.patenthub_budget import get_budget_status
    return await get_budget_status(str(round_id))


@router.post("/{project_id}/documents/{document_id}/upload-fulltext")
async def upload_document_fulltext(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    format: str = "pdf",
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户手动上传全文兜底（PDF 或 HTML）。

    format=pdf|html 决定写入哪个通道（fulltext_pdf_* / fulltext_html_*）。
    PDF 用 PyMuPDF/pdfplumber 提取文本；HTML 用 _strip_html_tags 提取纯文本。
    """
    from app.config import settings
    from app.services.fulltext_service import (
        extract_text,
        _strip_html_tags,
        _slugify,
        _project_dir_name,
    )
    import hashlib as _hashlib

    if format not in ("pdf", "html"):
        raise HTTPException(status_code=400, detail="format 必须是 pdf 或 html")

    await _verify_project(project_id, current_user.id, db)

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    fname = (file.filename or "").lower()
    if format == "pdf":
        if not fname.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="PDF 通道仅支持 .pdf 文件")
        ext = ".pdf"
    else:
        if not (fname.endswith(".html") or fname.endswith(".htm") or fname.endswith(".mhtml")):
            raise HTTPException(status_code=400, detail="HTML 通道仅支持 .html / .htm / .mhtml 文件")
        ext = ".html"

    content = await file.read()
    if len(content) < 200:
        raise HTTPException(status_code=400, detail="文件过小或损坏")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大（>50MB）")

    proj_r = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_r.scalar_one_or_none()
    project_title = project.title if project else None

    pdf_base = Path(getattr(settings, "pdf_storage_path", "./data/pdfs"))
    proj_dir = pdf_base / _project_dir_name(str(project_id), project_title)
    proj_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(doc.title)
    short_hash = _hashlib.md5(str(document_id).encode()).hexdigest()[:8]
    local_path = proj_dir / f"{slug}_{short_hash}{ext}"
    local_path.write_bytes(content)

    if format == "pdf":
        text = await extract_text(str(local_path))
        if not text:
            raise HTTPException(
                status_code=422,
                detail="无法从 PDF 提取文本（可能是扫描件或加密文档）",
            )
    else:
        try:
            html_str = content.decode("utf-8", errors="ignore")
        except Exception:
            html_str = ""
        text = _strip_html_tags(html_str) if html_str else ""
        if not text:
            raise HTTPException(
                status_code=422,
                detail="无法从 HTML 提取正文文本",
            )

    sanitized = text.replace("\x00", "")
    sanitized = "".join(
        ch for ch in sanitized
        if ch in ("\n", "\r", "\t") or ord(ch) >= 0x20
    )[:50000]

    if format == "pdf":
        doc.fulltext_pdf_path = str(local_path)
        doc.fulltext_pdf_status = "available"
    else:
        doc.fulltext_html_path = str(local_path)
        doc.fulltext_html_status = "available"

    doc.fulltext_status = "available"
    doc.fulltext_path = str(local_path)
    doc.fulltext_text = sanitized
    await db.commit()
    logger.info(
        "[Upload] doc=%s format=%s uploaded, %d chars extracted",
        document_id, format, len(sanitized),
    )

    return {
        "status": "ok",
        "format": format,
        "chars": len(sanitized),
        "message": f"已上传 {format.upper()} 并提取 {len(sanitized)} 字符全文，可点击「让 AI 重新分析」更新摘要",
    }


class RegenerateAnalysisRequest(BaseModel):
    hint: Optional[str] = None


@router.post("/{project_id}/documents/{document_id}/regenerate-analysis")
async def regenerate_document_analysis(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: RegenerateAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """让 AI 重新分析文档（同步 LLM 调用，基于全文 + 可选 hint 更新 ai_summary/ai_key_points）"""
    from app.services.llm_summarizer import LLMSummarizer
    from app.services.core.llm_config_store import get_llm_manager

    await _verify_project(project_id, current_user.id, db)

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    llm_manager = await get_llm_manager()
    summarizer = LLMSummarizer(llm_manager)

    doc_dict = {
        "title": doc.title,
        "abstract": doc.abstract,
        "fulltext_text": doc.fulltext_text,
    }

    # 把 hint 注入到 project_description，引导 LLM 关注用户方向
    project_desc = project.description or ""
    if req.hint:
        project_desc = f"{project_desc}\n\n用户重点关注方向: {req.hint}"

    try:
        summary, key_points, relevance_reason, summary_source = await summarizer.generate_summary(
            doc=doc_dict,
            project_description=project_desc,
            use_fulltext=bool(doc.fulltext_text),
        )
    except Exception as e:
        logger.error("[Regenerate] LLM 调用失败 doc=%s: %s", document_id, e)
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    if not summary:
        raise HTTPException(status_code=500, detail="重新分析失败：LLM 未返回有效结果")

    doc.ai_summary = summary
    doc.ai_key_points = key_points or []
    doc.ai_relevance_reason = relevance_reason
    doc.ai_summary_source = summary_source
    await db.commit()
    logger.info("[Regenerate] doc=%s updated via %s", document_id, summary_source)

    return {
        "status": "ok",
        "ai_summary": summary,
        "ai_key_points": key_points or [],
        "ai_relevance_reason": relevance_reason,
        "ai_summary_source": summary_source,
    }


class DocumentUpdateRequest(BaseModel):
    """
    用户手动编辑文献卡片。写入 _user 版本字段，AI 重新生成时不会覆盖这些值。
    特殊语义：
    - 字段值为 null → 不改（沿用原 _user 值）
    - 字段值为空字符串 / 空数组 → 显式撤销覆盖（清空 _user 回到 AI 版）
    - 字段值为非空内容 → 写入 _user 覆盖
    """
    one_line_summary: Optional[str] = None
    ai_key_points: Optional[List[str]] = None
    ai_summary: Optional[str] = None
    # 次要：非用户覆盖语义，直接写 _ai 字段
    ai_relevance_reason: Optional[str] = None


@router.patch("/{project_id}/documents/{document_id}")
async def update_document_fields(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: DocumentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    用户手动编辑卡片字段。保存到 _user 版本，不覆盖 AI 原版。
    展示时由 _effective_document_view 合并：_user 非空优先，否则用 _ai。
    """
    await _verify_project(project_id, current_user.id, db)

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 严格字段映射（req 字段名 → Document 列名）
    user_field_map = {
        "one_line_summary": "one_line_summary_user",
        "ai_key_points": "ai_key_points_user",
        "ai_summary": "ai_summary_user",
    }

    raw = req.model_dump(exclude_unset=True)  # 只取显式发送的字段
    if not raw:
        raise HTTPException(status_code=400, detail="未提供任何更新字段")

    updated_cols: list[str] = []
    for api_key, val in raw.items():
        if api_key in user_field_map:
            col = user_field_map[api_key]
            # 空字符串 / 空数组 → 清 _user 视为撤销覆盖
            if val is None:
                continue
            if (isinstance(val, str) and val.strip() == "") or (
                isinstance(val, list) and len(val) == 0
            ):
                setattr(doc, col, None)
            else:
                setattr(doc, col, val)
            updated_cols.append(col)
        elif api_key == "ai_relevance_reason" and val is not None:
            doc.ai_relevance_reason = val
            updated_cols.append("ai_relevance_reason")

    if not updated_cols:
        raise HTTPException(status_code=400, detail="未提供任何有效更新")

    await db.commit()
    logger.info(
        "[PatchDoc] doc=%s user-edit fields=%s",
        document_id, updated_cols,
    )

    return {"status": "ok", "id": str(doc.id), **_effective_document_view(doc)}


class ApplyAiUpdateRequest(BaseModel):
    """接受 LLM 的卡片更新建议，写入 _ai 字段（不覆盖 _user，用户编辑永远优先）"""
    field: str           # "one_line_summary" | "ai_summary" | "ai_key_points"
    new_value: object    # str 或 list[str]
    reason: Optional[str] = None


@router.post("/{project_id}/documents/{document_id}/ai-apply-update")
async def apply_ai_update(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: ApplyAiUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    接受 LLM 的卡片更新建议。写 _ai 字段（AI 版本），_user 保持不变。
    最终展示值 = _user (若存在) 或 _ai；因此若用户未编辑过该字段，这次更新会立刻生效。
    """
    await _verify_project(project_id, current_user.id, db)

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    VALID = {"one_line_summary", "ai_summary", "ai_key_points"}
    if req.field not in VALID:
        raise HTTPException(status_code=400, detail=f"不支持的字段: {req.field}")

    if req.field == "ai_key_points":
        if not isinstance(req.new_value, list):
            raise HTTPException(status_code=400, detail="ai_key_points 必须是列表")
        cleaned = [str(s).strip()[:300] for s in req.new_value if str(s).strip()][:20]
        doc.ai_key_points = cleaned or None
    else:
        if not isinstance(req.new_value, str):
            raise HTTPException(status_code=400, detail=f"{req.field} 必须是字符串")
        v = req.new_value.strip()[:5000] or None
        setattr(doc, req.field, v)

    # 标记 source 为 AI 提议 + 用户接受
    doc.ai_summary_source = "from_ai_suggestion"
    await db.commit()
    logger.info(
        "[ApplyAiUpdate] doc=%s field=%s reason=%s",
        document_id, req.field, (req.reason or "")[:80],
    )
    return {"status": "ok", "id": str(doc.id), **_effective_document_view(doc)}


def _effective_document_view(doc: Document) -> dict:
    """
    合并 _user / _ai 字段，返回前端展示用的"有效值"视图 + 编辑标记。
    用于 PATCH 响应、card 展示、协作 prompt 组装等所有需要"用户视角"的地方。
    """
    edited: list[str] = []
    if doc.one_line_summary_user is not None:
        edited.append("one_line_summary")
    if doc.ai_key_points_user is not None:
        edited.append("ai_key_points")
    if doc.ai_summary_user is not None:
        edited.append("ai_summary")
    return {
        "one_line_summary": doc.one_line_summary_user or doc.one_line_summary,
        "ai_key_points": (
            doc.ai_key_points_user
            if doc.ai_key_points_user is not None
            else (doc.ai_key_points or [])
        ),
        "ai_summary": doc.ai_summary_user or doc.ai_summary,
        "ai_relevance_reason": doc.ai_relevance_reason,
        "user_edited_fields": edited,
        # 暴露 AI 原版供前端"对比/回退"使用
        "one_line_summary_ai": doc.one_line_summary,
        "ai_key_points_ai": doc.ai_key_points or [],
        "ai_summary_ai": doc.ai_summary,
    }


# ──────────── Helpers ────────────

async def _verify_project(project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="项目不存在")


async def _get_active_round_id(project_id: uuid.UUID, db: AsyncSession):
    """获取当前活跃轮次 ID（用于记录分类来源）"""
    from app.models.search_round import SearchRound
    result = await db.execute(
        select(SearchRound.id)
        .where(SearchRound.project_id == project_id)
        .order_by(SearchRound.round_number.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


@router.get("/{project_id}/documents/{document_id}/file")
async def serve_fulltext_file(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    format: str | None = None,  # "pdf" | "html" | None（自动：PDF 优先）
    current_user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """
    返回已下载到本地的全文文件（PDF 或 HTML）。

    format (query):
      - "pdf"  : 强制返回 PDF 通道
      - "html" : 强制返回 HTML 通道
      - None   : PDF 优先，fallback 到 HTML，再 fallback 到旧 fulltext_path
    """
    from pathlib import Path
    await _verify_project(project_id, current_user.id, db)

    res = await db.execute(select(Document).where(Document.id == document_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 按 format 选择路径
    chosen: str | None = None
    if format == "pdf":
        chosen = doc.fulltext_pdf_path
        if not chosen:
            raise HTTPException(status_code=404, detail="该文献尚无 PDF 格式")
    elif format == "html":
        chosen = doc.fulltext_html_path
        if not chosen:
            raise HTTPException(status_code=404, detail="该文献尚无 HTML 格式")
    else:
        # 自动：PDF 优先
        chosen = doc.fulltext_pdf_path or doc.fulltext_html_path or doc.fulltext_path

    if not chosen:
        raise HTTPException(status_code=404, detail="该文献尚无本地全文")

    file_path = Path(chosen)
    if not file_path.exists():
        # 自愈：物理文件被手动清理 → 重置 DB 状态，让前端可重新下载
        suffix = file_path.suffix.lower()
        reset_any = False
        if doc.fulltext_pdf_path == chosen or suffix == ".pdf":
            doc.fulltext_pdf_path = None
            doc.fulltext_pdf_status = "failed"
            reset_any = True
        if doc.fulltext_html_path == chosen or suffix in (".html", ".htm"):
            doc.fulltext_html_path = None
            doc.fulltext_html_status = "failed"
            reset_any = True
        if doc.fulltext_path == chosen:
            doc.fulltext_path = None
            reset_any = True
        # 任何一路 path 都没了 → fulltext_status 回落
        if not (doc.fulltext_pdf_path or doc.fulltext_html_path or doc.fulltext_path):
            doc.fulltext_status = "failed"
            reset_any = True
        if reset_any:
            await db.commit()
            logger.warning(
                "[serve_fulltext] file missing, reset doc %s (path=%s)", doc.id, chosen
            )
        raise HTTPException(status_code=404, detail="本地全文文件已丢失，已重置可重新下载")

    # Detect media type by extension
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix in (".html", ".htm"):
        media_type = "text/html"
    else:
        media_type = "application/octet-stream"

    # 关键：HTTP headers 必须是 latin-1，含中文的 filename 需要走 RFC 5987
    # filename*=UTF-8''<percent-encoded> 格式，否则 starlette 写入 header 时 500。
    # 同时给一个 ASCII fallback filename（doc id 前缀）兼容老浏览器。
    from urllib.parse import quote
    ascii_fallback = f"document_{document_id}{suffix}"
    encoded_name = quote(file_path.name, safe="")
    content_disposition = (
        f'inline; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{encoded_name}"
    )

    # 0028: 用户成功拿到 binary → 自动记 ownership（多设备同步基础）
    # 失败静默：不阻塞 binary 返回（用户拿到文件优先于记录簿对账）
    try:
        from app.api.user_documents import mark_owned
        owned_format = "pdf" if suffix == ".pdf" else "html" if suffix in (".html", ".htm") else None
        if owned_format:
            await mark_owned(
                db,
                user_id=current_user.id,
                project_id=project_id,
                document_id=document_id,
                source="downloaded",
                format=owned_format,
            )
    except Exception as e:
        logger.warning(f"[serve_fulltext] mark_owned failed (non-fatal): {e}")

    # FileResponse(filename=...) 也会写 Content-Disposition，所以这里不传 filename，
    # 自己用 headers 覆盖，避免 starlette 内部对中文 filename 做 latin-1 encode 失败。
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={"Content-Disposition": content_disposition},
    )
