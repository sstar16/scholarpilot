"""
Crossref 引用关系抓取。

Crossref API: GET https://api.crossref.org/works/{doi}?mailto=...&select=reference
- 响应 message.reference[] 每项可能含 DOI 或纯文本 citation
- 只保留带 DOI 的项
- polite pool：mailto + UA 走加速通道
"""
from __future__ import annotations

import logging
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.crossref.org/works/{doi}"
_MAILTO = "lzhd553@gmail.com"  # polite pool
_TIMEOUT = 15.0
_USER_AGENT = f"scholarpilot/1.0 (mailto:{_MAILTO})"


def _normalize_doi(doi: str) -> Optional[str]:
    if not doi:
        return None
    d = doi.strip().lower()
    # 有些 doi 带 https://doi.org/ 前缀
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d or None


async def fetch_references_dois(doi: str) -> List[str]:
    """
    查询 Crossref，返回该 DOI 引用的作品的 DOI 列表。
    失败 / 无引用 / 无 DOI 的引用 → 返回空列表（永不 raise）。
    """
    norm = _normalize_doi(doi or "")
    if not norm:
        return []

    url = _BASE.format(doi=norm)
    headers = {"User-Agent": _USER_AGENT}
    params = {"mailto": _MAILTO, "select": "reference"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            r = await client.get(url, params=params)
            if r.status_code == 404:
                logger.info("[citation_fetcher] doi=%s not in Crossref", norm)
                return []
            r.raise_for_status()
            data = r.json() or {}
    except httpx.HTTPStatusError as e:
        logger.info(
            "[citation_fetcher] doi=%s HTTP %s", norm, e.response.status_code,
        )
        return []
    except Exception as e:
        logger.warning("[citation_fetcher] doi=%s failed: %s", norm, e)
        return []

    refs = ((data.get("message") or {}).get("reference") or [])
    out: List[str] = []
    seen: set = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        d_raw = ref.get("DOI")
        d = _normalize_doi(d_raw or "")
        if not d or d in seen or d == norm:
            continue
        seen.add(d)
        out.append(d)
    return out
