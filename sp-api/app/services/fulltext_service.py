"""
Fulltext Service — sp-api 客户端版本（**零本地 PDF 写**改造，2026-05-08）。

设计变化（vs 之前 base64 把 PDF 写本地再转回客户端）：
- 不再写 ``/app/data/pdfs``。客户端拿 PDF 的方式分三类：
    A 类 OA 直链（arxiv/openalex/europe_pmc/crossref/semantic_scholar）
        → fetcher 已返 ``pdf_url``，客户端 Rust 直接抓，sp-api 完全不参与。
    B 类 landing-meta（pubmed/dblp/clinical_trials/openalex_zh）
        → ``resolve_pdf_url`` 解析 doi/landing 上的 ``citation_pdf_url`` meta
          或走 unpaywall，**只返回 URL 字符串**，binary 由客户端 Rust 自抓。
    C 类 付费 token（patenthub/lens/epo_ops/bigquery_patents）
        → ``stream_pdf_proxy`` 用 sp-api 服务端 token 调付费 API，
          httpx 流式 GET 拿响应 → 异步 yield bytes chunks 给上游
          ``StreamingResponse`` 转发给客户端。**绝对不调 ``write_bytes``**。

任何 ``write_bytes`` / ``aiofiles.open`` / ``tokio::fs::write`` 都不应该
出现在这个模块或下游 worker 路径里 —— grep 验证脚本会卡死它。

废弃字段：
- ``DEFAULT_PDF_BASE`` / ``download_pdf`` / ``download_html_fallback`` /
  ``download_and_extract`` / ``extract_text`` / ``_save_pdf_bytes`` 全部移除。
  patenthub fetcher 的 ``download_pdf_for_doc`` 还在 fetcher 类里（保留兼容
  Lens / EPO 后续若也接付费 PDF），但 fulltext_service 不再调用它 —
  C 类付费源 PDF 通过 ``stream_pdf_proxy`` 直接拿底层付费 API 的 stream。
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# 完整 Chrome 136 真实 fingerprint（参考 MediaCrawler 反爬策略） — 仅给
# resolve_pdf_url 用，因为它需要伪装成浏览器去抓 landing HTML。C 类 stream
# proxy 用各自付费源原生 header（token 鉴权 + JSON Accept）。
_CHROME_VERSION = "136.0.7103.114"
_BROWSER_HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-full-version-list": (
        f'"Chromium";v="{_CHROME_VERSION}", '
        f'"Google Chrome";v="{_CHROME_VERSION}", '
        '"Not.A/Brand";v="99.0.0.0"'
    ),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"19.0.0"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Priority": "u=0, i",
}


# ─── 共享小工具 ────────────────────────────────────────────────────────────


def _normalize_doi(raw: Optional[str]) -> Optional[str]:
    """剥掉 DOI 字符串的所有 URL 前缀，避免 'https://doi.org/https://doi.org/...' 双重前缀。"""
    if not raw:
        return None
    s = str(raw).strip()
    for _ in range(3):
        low = s.lower()
        stripped = False
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if low.startswith(prefix):
                s = s[len(prefix):].strip()
                stripped = True
                break
        if not stripped:
            break
    return s or None


def _html_headers(referer: Optional[str] = None) -> dict:
    h = dict(_BROWSER_HEADERS_BASE)
    h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    if referer:
        h["Referer"] = referer
    return h


_CITATION_PDF_RE = re.compile(
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_CITATION_PDF_RE_SWAPPED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
    re.IGNORECASE,
)


def _extract_citation_pdf(html: str) -> Optional[str]:
    """两种属性顺序都支持。"""
    if not html:
        return None
    m = _CITATION_PDF_RE.search(html) or _CITATION_PDF_RE_SWAPPED.search(html)
    return m.group(1) if m else None


def _absolutize(landing_url: str, candidate: str) -> str:
    """``citation_pdf_url`` 偶尔是相对路径，按 landing 拼绝对。"""
    if candidate.startswith(("http://", "https://")):
        return candidate
    from urllib.parse import urljoin
    return urljoin(landing_url, candidate)


# ─── B 类：resolve_pdf_url（landing meta + unpaywall，纯返 URL） ────────


async def unpaywall_lookup(doi: str) -> Optional[str]:
    """OA 仓库 PDF URL 探测，仅返字符串。"""
    doi = _normalize_doi(doi)
    if not doi:
        return None
    try:
        from urllib.parse import quote
        from app.config import settings
        email = (getattr(settings, "unpaywall_email", None) or "").strip()
        if not email:
            email = "scholarpilot@example.com"
        encoded = quote(doi, safe="")
        url = f"https://api.unpaywall.org/v2/{encoded}?email={email}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_BROWSER_HEADERS_BASE)
            if resp.status_code == 200:
                data = resp.json()
                best = data.get("best_oa_location") or {}
                pdf = best.get("url_for_pdf") or best.get("url")
                if pdf:
                    logger.info("[Fulltext] Unpaywall OA found for %s", doi)
                    return pdf
            else:
                logger.warning(
                    "[Fulltext] Unpaywall returned %d for doi=%s",
                    resp.status_code, doi,
                )
    except Exception as e:
        logger.warning("[Fulltext] Unpaywall lookup failed for %s: %r", doi, e)
    return None


async def _extract_citation_pdf_from_landing(
    client: httpx.AsyncClient, landing_url: str
) -> Optional[str]:
    try:
        resp = await client.get(landing_url, headers=_html_headers())
        if resp.status_code != 200:
            logger.warning(
                "[Fulltext] Landing rejected status=%d url=%s",
                resp.status_code, landing_url,
            )
            return None
        candidate = _extract_citation_pdf(resp.text)
        if candidate:
            absolute = _absolutize(str(resp.url), candidate)
            logger.info("[Fulltext] citation_pdf_url=%s (from %s)", absolute, landing_url)
            return absolute
        return None
    except Exception as e:
        logger.warning("[Fulltext] Landing fetch failed %s: %r", landing_url, e)
        return None


async def resolve_pdf_url(
    source: Optional[str],
    external_id: Optional[str],
    doi: Optional[str],
    landing_url: Optional[str],
    pdf_url: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    B 类源解析 → 返回 PDF URL（不下载 binary）。

    返回字段：
        ``pdf_url``     拿到的绝对 URL，无解析结果时为 ``None``
        ``source_layer`` ``'direct'`` / ``'unpaywall'`` / ``'doi-meta'`` /
                          ``'landing-meta'`` / ``None``

    路径优先级（任一命中即返回）：
        1. 调用方已带 ``pdf_url`` → 直接回（客户端可能也想让 sp-api 校验，
           但我们不下载，直接 echo + layer='direct'）
        2. ``doi`` → unpaywall
        3. ``doi`` → ``doi.org/{doi}`` HTML 抓 ``citation_pdf_url`` meta
        4. ``landing_url`` HTML 抓 ``citation_pdf_url`` meta

    所有 strategy 失败时 ``pdf_url=None / source_layer=None``。
    """
    if pdf_url:
        return {"pdf_url": pdf_url, "source_layer": "direct"}

    doi_norm = _normalize_doi(doi)

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers=_BROWSER_HEADERS_BASE,
    ) as client:
        if doi_norm:
            oa = await unpaywall_lookup(doi_norm)
            if oa:
                return {"pdf_url": oa, "source_layer": "unpaywall"}
            cite = await _extract_citation_pdf_from_landing(
                client, f"https://doi.org/{doi_norm}",
            )
            if cite:
                return {"pdf_url": cite, "source_layer": "doi-meta"}

        if landing_url:
            cite = await _extract_citation_pdf_from_landing(client, landing_url)
            if cite:
                return {"pdf_url": cite, "source_layer": "landing-meta"}

    logger.info(
        "[Fulltext] resolve_pdf_url 无解析结果 source=%s ext=%s doi=%s landing=%s",
        source, external_id, doi_norm, landing_url,
    )
    return {"pdf_url": None, "source_layer": None}


# ─── C 类：stream_pdf_proxy（付费源 token，stream 转发不落盘） ────────────


async def _stream_patenthub_pdf(
    fetcher, external_id: str, chunk_size: int,
) -> AsyncIterator[bytes]:
    """patenthub 三段式：详情 → pdfList[0] → /api/pdf 流式 GET。

    sp-api 服务端持 token，调用 fetcher.get_detail 拿 pdf_key（详情接口收 ¥0.1），
    然后 stream /api/pdf（PDF 接口收 ¥1）。**不写 disk**：httpx ``stream`` 上下文
    管理器拿 response 后直接 ``aiter_bytes`` 转发。
    """
    detail = await fetcher.get_detail(external_id)
    if not detail:
        raise ValueError(f"patenthub detail failed: {external_id}")
    pdf_list = detail.get("pdfList") or []
    if not pdf_list:
        raise ValueError(f"patenthub no pdfList: {external_id}")
    pdf_key = pdf_list[0]
    token = await fetcher._get_token()
    if not token or not pdf_key:
        raise ValueError("patenthub missing token / pdf_key")

    from app.services.fetchers.patenthub import PATENTHUB_PDF_URL
    params = {"t": token, "v": "1", "key": pdf_key}

    # 用一次性 client 而不是 fetcher._http_client() — 避免把 share-singleton
    # 的连接占在长 stream 上导致其他 fetcher 调用堵塞。
    async with httpx.AsyncClient(timeout=fetcher.PDF_DOWNLOAD_TIMEOUT) as client:
        async with client.stream("GET", PATENTHUB_PDF_URL, params=params) as resp:
            if resp.status_code != 200:
                body = (await resp.aread())[:200]
                raise RuntimeError(
                    f"patenthub /api/pdf HTTP {resp.status_code}: {body!r}"
                )
            magic_checked = False
            async for chunk in resp.aiter_bytes(chunk_size=chunk_size):
                if not chunk:
                    continue
                if not magic_checked:
                    if not chunk.startswith(b"%PDF-"):
                        # 头几个字节不是 PDF magic — 付费 API 可能返 JSON
                        # 错误（额度耗尽等）。立刻抛错让上游 refund。
                        raise RuntimeError(
                            f"patenthub /api/pdf returned non-PDF body: {chunk[:80]!r}"
                        )
                    magic_checked = True
                yield chunk


async def stream_pdf_proxy(
    source: str,
    external_id: Optional[str],
    pdf_url: Optional[str] = None,
    doi: Optional[str] = None,
    chunk_size: int = 64 * 1024,
) -> AsyncIterator[bytes]:
    """
    C 类付费源 PDF 流式代理。

    sp-api 用服务端 token 调底层付费 API，httpx ``stream`` 拿到上游 response
    后立刻 ``aiter_bytes`` 转发给调用方（``StreamingResponse``），全程不落盘。

    支持的 source：当前仅 ``patenthub``（lens/epo_ops/bigquery_patents 的付费 PDF
    端点等加进来时再扩 dispatch）。

    Raises:
        ValueError: 源未知 / 详情拉不到 / 缺 external_id
        RuntimeError: 上游付费 API 返非 PDF / HTTP 错误
    """
    from app.services.fetchers.international import ALL_FETCHERS

    fetcher = ALL_FETCHERS.get(source)
    if fetcher is None:
        raise ValueError(f"未知 source '{source}'")
    if not getattr(fetcher, "PAID_PDF", False):
        raise ValueError(f"source '{source}' 不是付费源，应走 resolve_pdf_url")

    if source == "patenthub":
        if not external_id:
            raise ValueError("patenthub 需要 external_id (patent number)")
        async for chunk in _stream_patenthub_pdf(fetcher, external_id, chunk_size):
            yield chunk
        return

    raise ValueError(f"付费源 '{source}' 未实现 stream_pdf_proxy dispatch")
