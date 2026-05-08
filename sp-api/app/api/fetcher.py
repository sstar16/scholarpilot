"""Fetcher API — sp-api 数据源代理桥。

客户端 BYOK 路线：客户端不直连 14 数据源（避免 CN GFW / Lens.org / EPO 鉴权
等环境差异），改走 sp-api（HK 机器）做 fetcher 代理 + patenthub 预算守门。

路由：
  GET  /api/fetcher/sources                      - 列源元数据 + 启用/禁用状态
  POST /api/fetcher/search                       - 单源检索 → List[doc]
  POST /api/fetcher/budget/patenthub/check       - 不消费仅查
  POST /api/fetcher/budget/patenthub/consume     - 消费 1 次（force=true 越权）
  POST /api/fetcher/budget/patenthub/refund      - 失败回退
"""
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.dependencies import get_current_user
from app.models.user import User
from app.services.fetchers.base import FetcherRegistry
from app.services.fetchers.international import ALL_FETCHERS
from app.services.patenthub_budget import (
    derive_budget_key,
    get_budget_status,
    refund as budget_refund,
    try_consume,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fetcher", tags=["fetcher"])
limiter = Limiter(key_func=get_remote_address)


# ── Schemas ──────────────────────────────────────────────────


class SourceInfo(BaseModel):
    id: str
    name: str
    description: str
    doc_type: str
    category: str
    language: str
    phase: int
    enabled: bool
    paid_pdf: bool


class SearchRequest(BaseModel):
    source: str
    # QueryPlanAgent agentic 模式生成的 boolean query（"(A OR B) AND (C OR D) ..."）
    # 常 800+ 字符；500 上限会让客户端 fetch 全部 400。OpenAlex/Crossref/PubMed
    # 等 API 都接受 1k+ 字符 query。设 2000 留余量，2026-05-08 from 500 raised.
    keywords: str = Field(..., min_length=1, max_length=2000)
    max_results: int = Field(20, ge=1, le=200)
    year_from: Optional[int] = Field(None, ge=1900, le=2100)
    year_to: Optional[int] = Field(None, ge=1900, le=2100)
    language: Optional[str] = None


class SearchResponse(BaseModel):
    source: str
    count: int
    docs: list[dict[str, Any]]


class BudgetKeyRequest(BaseModel):
    client_run_id: str = Field(..., min_length=1, max_length=128)


class BudgetConsumeRequest(BudgetKeyRequest):
    force: bool = False


class BudgetStatus(BaseModel):
    used: int
    max: int
    remaining: int
    exhausted: bool


class BudgetConsumeResponse(BaseModel):
    ok: bool
    used: int
    max: int
    refunded: bool = False


# ── Helpers ──────────────────────────────────────────────────


def _disabled_set() -> set[str]:
    raw = os.getenv("DISABLED_SOURCES", "") or ""
    return {s.strip() for s in raw.split(",") if s.strip()}


# ── Endpoints ────────────────────────────────────────────────


@router.get("/sources", response_model=list[SourceInfo])
async def list_sources(_user: User = Depends(get_current_user)):
    """列 14 源元数据 + 启用/禁用状态（客户端 UI 渲染勾选框用）。"""
    disabled = _disabled_set()
    items: list[SourceInfo] = []
    for entry in FetcherRegistry.get_all_info():
        sid = entry["id"]
        fetcher = ALL_FETCHERS.get(sid)
        items.append(SourceInfo(
            id=sid,
            name=entry["name"],
            description=entry["description"],
            doc_type=entry["doc_type"],
            category=entry["category"],
            language=entry["language"],
            phase=entry["phase"],
            enabled=(sid not in disabled) and (fetcher is not None),
            paid_pdf=bool(getattr(fetcher, "PAID_PDF", False)) if fetcher else False,
        ))
    return items


@router.post("/search", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search_source(
    req: SearchRequest,
    request: Request,
    _user: User = Depends(get_current_user),
):
    """单源检索 — 直接调 ALL_FETCHERS[source].safe_fetch(query, max_results, ...)。"""
    if req.source in _disabled_set():
        raise HTTPException(status_code=400, detail=f"source '{req.source}' 已禁用")
    fetcher = ALL_FETCHERS.get(req.source)
    if fetcher is None:
        raise HTTPException(status_code=400, detail=f"未知 source '{req.source}'")

    try:
        sid, docs = await fetcher.safe_fetch(
            query=req.keywords,
            max_results=req.max_results,
            year_from=req.year_from,
            year_to=req.year_to,
            language=req.language,
        )
    except Exception as e:
        logger.exception("[fetcher] %s search failed", req.source)
        raise HTTPException(status_code=502, detail=f"{req.source}: {type(e).__name__}: {e}")

    return SearchResponse(source=sid, count=len(docs), docs=docs)


@router.post("/budget/patenthub/check", response_model=BudgetStatus)
async def patenthub_check(
    req: BudgetKeyRequest,
    current_user: User = Depends(get_current_user),
):
    """不消费仅查 — 前端"剩余 N/5"展示用。"""
    key = derive_budget_key(req.client_run_id, str(current_user.id))
    status = await get_budget_status(key)
    return BudgetStatus(**{k: v for k, v in status.items() if k in ("used", "max", "remaining", "exhausted")})


@router.post("/budget/patenthub/consume", response_model=BudgetConsumeResponse)
async def patenthub_consume(
    req: BudgetConsumeRequest,
    current_user: User = Depends(get_current_user),
):
    """消费 1 次（force=true 用户二次确认越权）。

    返回 ok=False 表示软超额 — 前端弹二次确认弹窗，用户选"继续"再带 force=true 重发。
    """
    key = derive_budget_key(req.client_run_id, str(current_user.id))
    ok, used, mx = await try_consume(key, force=req.force)
    return BudgetConsumeResponse(ok=ok, used=used, max=mx)


@router.post("/budget/patenthub/refund", response_model=BudgetConsumeResponse)
async def patenthub_refund(
    req: BudgetKeyRequest,
    current_user: User = Depends(get_current_user),
):
    """失败回退 1 次（client 下载失败时调）。"""
    key = derive_budget_key(req.client_run_id, str(current_user.id))
    await budget_refund(key)
    status = await get_budget_status(key)
    return BudgetConsumeResponse(
        ok=True,
        used=status["used"],
        max=status["max"],
        refunded=True,
    )
