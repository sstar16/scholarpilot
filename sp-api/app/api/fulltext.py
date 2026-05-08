"""Fulltext API — sp-api PDF 全文桥（**零本地 PDF 写**版本，2026-05-08）。

**重要**：sp-api 不再缓存 / 落盘 / 解析 PDF。客户端 Tauri Rust 自行下载 PDF
到 ``<AppData>/scholarpilot/projects/<pid>/pdfs/<docId>.pdf``。这里只做两件事：

1. **B 类 OA（DBLP / PubMed / ClinicalTrials / OpenAlex_zh）**
   ``POST /api/fulltext/resolve-url``
     body  {source, external_id, doi, landing_url, pdf_url?}
     resp  {pdf_url: str | null, source_layer: 'direct'|'unpaywall'|'doi-meta'|'landing-meta'|null}
   服务端只做 HTML meta 抓取 + unpaywall lookup，返 URL 字符串。binary 由
   客户端 Rust ``reqwest::get`` 自抓，避免 cloudflared single-response 上限 +
   sp-api 内存压力。

2. **C 类付费 token（PatentHub）**
   ``POST /api/fulltext/proxy/{source}/{external_id}``
     body  {client_run_id, force?, doi?, pdf_url?}
     resp  StreamingResponse(application/pdf, chunked, **不落盘**)
   sp-api 用服务端 token 调付费 API（patenthub 三段式 ¥0.1 详情 + ¥1 PDF），
   httpx ``stream`` + ``aiter_bytes`` 转发给客户端。预算守门 try_consume 在
   stream 启动前消费，stream 异常时 refund。
   `chunk_size` 默认 64 KB → 100 MB PDF 占用 < 1 MB 常驻内存。

A 类（arxiv / openalex / europe_pmc / crossref）由客户端 Rust 直抓，根本不
经过 sp-api，没有路由。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import get_current_user
from app.models.user import User
from app.services.fetchers.international import ALL_FETCHERS
from app.services.fulltext_service import resolve_pdf_url, stream_pdf_proxy
from app.services.patenthub_budget import (
    derive_budget_key,
    refund as budget_refund,
    try_consume,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fulltext", tags=["fulltext"])


# ──────────────────────────────────────────────────────────────────────
# B 类: resolve-url（pure URL discovery, no binary）
# ──────────────────────────────────────────────────────────────────────


class ResolveUrlRequest(BaseModel):
    source: str = Field(..., description="数据源 id（dblp/pubmed/...）")
    external_id: Optional[str] = None
    doi: Optional[str] = None
    landing_url: Optional[str] = None
    pdf_url: Optional[str] = Field(
        None,
        description="若客户端已知直链，传进来 sp-api 会原样回 + layer='direct'",
    )


class ResolveUrlResponse(BaseModel):
    pdf_url: Optional[str] = None
    source_layer: Optional[str] = Field(
        None,
        description="解析层级：direct/unpaywall/doi-meta/landing-meta；解析失败为 null",
    )


@router.post("/resolve-url", response_model=ResolveUrlResponse)
async def resolve_url_endpoint(
    req: ResolveUrlRequest,
    _user: User = Depends(get_current_user),
):
    """B 类：解析 PDF 直链 URL，**不下载 binary**。

    客户端 Rust 拿到 ``pdf_url`` 后自行 ``reqwest::get`` 写本地。
    此端点设计成无副作用：可幂等重调，不消费付费配额。
    """
    if req.source in ALL_FETCHERS and getattr(
        ALL_FETCHERS[req.source], "PAID_PDF", False,
    ):
        # 付费源不该走 resolve-url（它们的 PDF URL 不是公开的）
        raise HTTPException(
            status_code=400,
            detail=f"source '{req.source}' 是付费源，应走 /api/fulltext/proxy/{{source}}/{{id}}",
        )
    try:
        result = await resolve_pdf_url(
            source=req.source,
            external_id=req.external_id,
            doi=req.doi,
            landing_url=req.landing_url,
            pdf_url=req.pdf_url,
        )
    except Exception as e:
        logger.exception("[fulltext] resolve_pdf_url failed source=%s", req.source)
        raise HTTPException(
            status_code=502, detail=f"{req.source}: {type(e).__name__}: {e}",
        )
    return ResolveUrlResponse(**result)


# ──────────────────────────────────────────────────────────────────────
# C 类: stream proxy（paid token, chunked passthrough, no disk）
# ──────────────────────────────────────────────────────────────────────


class ProxyRequest(BaseModel):
    client_run_id: str = Field(..., min_length=1, max_length=128)
    force: bool = Field(False, description="patenthub 二次确认越权")
    doi: Optional[str] = None
    pdf_url: Optional[str] = Field(
        None,
        description="若客户端已知直链且 fetcher 支持，可让 sp-api 直接 stream",
    )


def _safe_filename(source: str, external_id: str) -> str:
    """Content-Disposition 用：仅保留 ASCII alnum + '._-'."""
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "._-") else "_" for ch in external_id
    )[:80]
    return f"{source}_{cleaned or 'unknown'}.pdf"


@router.post("/proxy/{source}/{external_id}")
async def proxy_paid_pdf(
    req: ProxyRequest,
    source: str = Path(..., min_length=1, max_length=64),
    external_id: str = Path(..., min_length=1, max_length=200),
    current_user: User = Depends(get_current_user),
):
    """C 类付费源 PDF 流式代理 — sp-api 不落盘，chunked 转发给客户端。

    流程：
      1. 验证 source 是付费源（``PAID_PDF=True``）
      2. ``try_consume`` 守门：未越权且超额 → 402（前端弹二次确认）
      3. 启动底层付费 API stream → 包装成 ``StreamingResponse``
      4. stream body iterator 异常 → refund + 让 client 看到 connection error；
         成功 → 保留扣费

    **关键**：iterator 任何一段都不调用 ``write_bytes`` / ``aiofiles.open``。
    chunk_size=64 KB → 100 MB PDF 内存占用 stable < 1 MB。
    """
    fetcher = ALL_FETCHERS.get(source)
    if fetcher is None:
        raise HTTPException(status_code=400, detail=f"未知 source '{source}'")
    if not getattr(fetcher, "PAID_PDF", False):
        raise HTTPException(
            status_code=400,
            detail=f"source '{source}' 不是付费源，应走 /api/fulltext/resolve-url",
        )

    budget_key = derive_budget_key(req.client_run_id, str(current_user.id))
    ok, used, mx = await try_consume(budget_key, force=req.force)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "patenthub_budget_exceeded",
                "message": (
                    f"本轮 PatentHub PDF 已下载 {used}/{mx} 篇，"
                    f"是否继续？每篇约 ¥1.1（详情 0.1 + PDF 1.0）"
                ),
                "used": used,
                "max": mx,
                "cost_per_pdf": 1.1,
                "client_run_id": req.client_run_id,
            },
        )

    # 包一层 generator：stream 异常时 refund。注意 FastAPI 把 generator 在
    # response 发送阶段 iterate；若 stream_pdf_proxy 在第一个 chunk 之前就抛
    # （详情拿不到 / 余额不足），refund 必须命中。我们让 try/except 包住整个
    # for-loop（包括首次 __anext__），一抛就 refund。
    async def _gen() -> AsyncIterator[bytes]:
        try:
            async for chunk in stream_pdf_proxy(
                source=source,
                external_id=external_id,
                pdf_url=req.pdf_url,
                doi=req.doi,
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[fulltext] proxy stream failed source=%s ext=%s: %r",
                source, external_id, exc,
            )
            try:
                await budget_refund(budget_key)
            except Exception:
                pass
            # 在 generator 抛 → ASGI 中断 response，客户端看到 HTTPError
            raise

    headers = {
        "Content-Disposition": f'attachment; filename="{_safe_filename(source, external_id)}"',
        # X-* 头让客户端能感知预算扣费（避免再轮询 /budget/check）
        "X-Patenthub-Used": str(used),
        "X-Patenthub-Max": str(mx),
        "X-Source-Layer": "paid-stream",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(_gen(), media_type="application/pdf", headers=headers)
