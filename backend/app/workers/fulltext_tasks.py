"""
Celery tasks for batch fulltext download.
Triggered when documents are classified as very_relevant.
Only downloads OA papers. Rate limited to 5 concurrent.
"""
import asyncio
import logging
import uuid

from app.workers.celery_app import app as celery_app

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 5


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.workers.fulltext_tasks.download_single", bind=True, max_retries=1)
def download_single(
    self,
    document_id: str,
    project_id: str,
    format: str = "auto",
    patenthub_round_id: str | None = None,
):
    """Download fulltext for a single document.

    format: "auto" | "pdf" | "html"
    patenthub_round_id: 非 None 时表示 API 路由已**完成预扣费**（patenthub 守门），
        worker 只管下载；失败需 refund 回退。None = 非 patenthub 或无需守门。
    """
    return _run_async(_download_single_async(document_id, project_id, format, patenthub_round_id))


def _sanitize_fulltext_text(text: str | None) -> str:
    """PG UTF-8 不接受 \x00 null bytes，剔除控制字符（保留 \n\r\t），截 150k。

    上限从 50k 提到 150k（2026-05-03）：ProbeAgent 按 IMRaD section 切段 + LLM
    探针，要的是完整全文不是采样；早先 50k 设计针对 GPT-4 32K 上下文，现在 LLM
    都吃 100K-1M tokens。150K 字符 ≈ 40K tokens，覆盖 95%+ 学术 PDF 全量。
    """
    if not text:
        return ""
    s = text.replace("\x00", "")
    s = "".join(ch for ch in s if ch in ("\n", "\r", "\t") or ord(ch) >= 0x20)
    return s[:150_000]


async def _download_single_async(
    document_id: str,
    project_id: str,
    format: str = "auto",
    patenthub_round_id: str | None = None,
):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select, update
    from app.config import settings
    from app.models.document import Document
    from app.services.fulltext_service import download_and_extract
    from app.services.patenthub_budget import refund as patenthub_refund

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        try:
            result = await db.execute(
                select(Document).where(Document.id == uuid.UUID(document_id))
            )
            doc = result.scalar_one_or_none()
            if not doc:
                return {"error": "Document not found"}

            # 通道级幂等：如果用户已经有这种格式就跳过（用户想重试时前端先 reset 状态再触发）
            if format == "pdf" and doc.fulltext_pdf_status in ("available", "downloading"):
                return {"status": doc.fulltext_pdf_status, "format": "pdf", "skipped": True}
            if format == "html" and doc.fulltext_html_status in ("available", "downloading"):
                return {"status": doc.fulltext_html_status, "format": "html", "skipped": True}
            # auto 模式：两个通道都已 available 就跳过
            if format == "auto" and "available" in (doc.fulltext_pdf_status, doc.fulltext_html_status):
                return {"status": "available", "format": "auto", "skipped": True}

            # 查 project.title 用于生成可读的目录名
            from app.models.project import Project as _Proj
            proj_r = await db.execute(
                select(_Proj.title).where(_Proj.id == uuid.UUID(project_id))
            )
            proj_row = proj_r.first()
            project_title = proj_row[0] if proj_row else None

            # Mark as downloading（只标对应通道）
            _pre_values: dict = {"fulltext_status": "downloading"}
            if format in ("auto", "pdf"):
                _pre_values["fulltext_pdf_status"] = "downloading"
            if format in ("auto", "html"):
                _pre_values["fulltext_html_status"] = "downloading"
            await db.execute(
                update(Document).where(Document.id == doc.id).values(**_pre_values)
            )
            await db.commit()

            # Download — 返回 dict(pdf_path, pdf_text, html_path, html_text)
            # external_id 总是传，service 层按 fetcher.PAID_PDF 决定是否调付费下载分支。
            r = await download_and_extract(
                pdf_url=doc.pdf_url,
                doi=doc.doi,
                project_id=project_id,
                landing_url=doc.url,
                title=doc.title,
                project_title=project_title,
                format=format,
                source=doc.source,
                external_id=doc.external_id,
            )
            pdf_path = r.get("pdf_path")

            # PatentHub 失败时回退预算（API 路由已预扣费，下载失败就该还回去）
            if patenthub_round_id and not pdf_path:
                try:
                    await patenthub_refund(patenthub_round_id)
                    logger.info(
                        "[Fulltext] PatentHub PDF 失败，已 refund budget round=%s doc=%s",
                        patenthub_round_id[:8], document_id[:8],
                    )
                except Exception as _re:
                    logger.warning("[Fulltext] PatentHub refund 异常（非致命）: %r", _re)
            pdf_text = _sanitize_fulltext_text(r.get("pdf_text"))
            html_path = r.get("html_path")
            html_text = _sanitize_fulltext_text(r.get("html_text"))

            # 构造 update payload：按 format 决定要更新哪些通道字段
            values: dict = {}
            if format in ("auto", "pdf"):
                if pdf_path:
                    values["fulltext_pdf_path"] = pdf_path
                    values["fulltext_pdf_status"] = "available"
                else:
                    values["fulltext_pdf_status"] = "failed"
            if format in ("auto", "html"):
                if html_path:
                    values["fulltext_html_path"] = html_path
                    values["fulltext_html_status"] = "available"
                else:
                    values["fulltext_html_status"] = "failed"

            # 聚合 fulltext_status：任一 available → available，否则 failed
            # 读取当前 DB 状态，叠加本次写入后判断
            new_pdf_status = values.get("fulltext_pdf_status", doc.fulltext_pdf_status)
            new_html_status = values.get("fulltext_html_status", doc.fulltext_html_status)
            if "available" in (new_pdf_status, new_html_status):
                values["fulltext_status"] = "available"
                # fulltext_path 兼容字段：PDF 优先，否则 HTML
                preferred = pdf_path or doc.fulltext_pdf_path or html_path or doc.fulltext_html_path
                if preferred:
                    values["fulltext_path"] = preferred
            elif "downloading" in (new_pdf_status, new_html_status):
                values["fulltext_status"] = "downloading"
            else:
                values["fulltext_status"] = "failed"

            # fulltext_text 用主通道的文本（PDF 优先）
            if pdf_text:
                values["fulltext_text"] = pdf_text
            elif html_text and not (doc.fulltext_text and len(doc.fulltext_text) > len(html_text)):
                # 不覆盖已有更长的 PDF 文本
                values["fulltext_text"] = html_text

            await db.execute(update(Document).where(Document.id == doc.id).values(**values))
            await db.commit()

            logger.info(
                "[Fulltext] Downloaded doc=%s format=%s → pdf=%s html=%s status=%s",
                document_id[:8], format,
                pdf_path.rsplit("/", 1)[-1] if pdf_path else "-",
                html_path.rsplit("/", 1)[-1] if html_path else "-",
                values["fulltext_status"],
            )

            return {
                "status": values["fulltext_status"],
                "format": format,
                "pdf_path": pdf_path,
                "html_path": html_path,
                "pdf_chars": len(pdf_text),
                "html_chars": len(html_text),
            }

        except Exception as e:
            logger.error("[Fulltext] Download failed for doc=%s: %s", document_id[:8], e)
            try:
                _fail_values: dict = {}
                if format in ("auto", "pdf"):
                    _fail_values["fulltext_pdf_status"] = "failed"
                if format in ("auto", "html"):
                    _fail_values["fulltext_html_status"] = "failed"
                # 重新聚合：查当前通道状态，保留另一通道已成功的状态
                row = (await db.execute(
                    select(Document.fulltext_pdf_status, Document.fulltext_html_status)
                    .where(Document.id == uuid.UUID(document_id))
                )).first()
                if row:
                    new_pdf = _fail_values.get("fulltext_pdf_status", row.fulltext_pdf_status)
                    new_html = _fail_values.get("fulltext_html_status", row.fulltext_html_status)
                    if "available" in (new_pdf, new_html):
                        _fail_values["fulltext_status"] = "available"
                    elif "downloading" in (new_pdf, new_html):
                        _fail_values["fulltext_status"] = "downloading"
                    else:
                        _fail_values["fulltext_status"] = "failed"
                else:
                    _fail_values["fulltext_status"] = "failed"
                await db.execute(
                    update(Document).where(Document.id == uuid.UUID(document_id)).values(**_fail_values)
                )
                await db.commit()
            except Exception:
                pass
            return {"error": str(e)}
    await engine.dispose()
