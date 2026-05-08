"""Zenodo 数据源 Fetcher

GET `https://zenodo.org/api/records` — 学术 dataset / software / publication。
弥补 ScholarPilot 当前只有"论文/专利"维度，扩出"科研数据 + 软件"维度。

Inspired by: LDR `search_engine_zenodo.py`（无鉴权 / 自定义 UA）
ScholarPilot 改动：复用基类 httpx 连接池；resource_type 写到 metadata，
统一 doc_type="dataset"（避免新 enum；publication 子类型保留在 metadata）。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

ZENODO_ENDPOINT = "https://zenodo.org/api/records"


class ZenodoFetcher(AbstractFetcher):
    source_id = "zenodo"
    DEFAULT_TIMEOUT = 20.0

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        params = {
            "q": query,
            "size": min(max_results, 100),
            "sort": "bestmatch",
        }
        if year_from or year_to:
            yfrom = year_from or 1900
            yto = year_to or 2100
            # Zenodo Lucene query 支持 publication_date:[YYYY TO YYYY]
            params["q"] = f"({query}) AND publication_date:[{yfrom} TO {yto}]"

        papers: List[Dict] = []
        async with self._http_client(headers={"User-Agent": "ScholarPilot/2.0 (scholarpilot@example.com)"}) as client:
            try:
                r = await client.get(ZENODO_ENDPOINT, params=params)
                if r.status_code != 200:
                    logger.warning("[Zenodo] HTTP %d: %s", r.status_code, r.text[:200])
                    return []
                hits = (r.json() or {}).get("hits", {}).get("hits", []) or []
                for rec in hits[:max_results]:
                    meta = rec.get("metadata", {}) or {}
                    rid = rec.get("id") or ""
                    title = meta.get("title") or ""
                    creators = meta.get("creators") or []
                    authors = ", ".join([(c.get("name") or "") for c in creators[:5]])
                    if len(creators) > 5:
                        authors += " et al."
                    description = meta.get("description") or ""
                    if description:
                        # Zenodo description 经常是 HTML
                        import re as _re
                        description = _re.sub(r"<[^>]+>", "", description).strip()
                    doi = (meta.get("doi") or rec.get("doi") or "")
                    pub_date = meta.get("publication_date")
                    resource_type = (meta.get("resource_type") or {}).get("type") or ""
                    keywords = meta.get("keywords") or []
                    license_id = (meta.get("license") or {}).get("id") if isinstance(meta.get("license"), dict) else None
                    links = rec.get("links", {}) or {}
                    self_html = links.get("self_html") or links.get("html")
                    papers.append({
                        "source": "zenodo",
                        "external_id": str(rid),
                        "doc_type": "dataset",  # 统一标记
                        "title": title,
                        "authors": authors,
                        "abstract": description,
                        "publication_date": pub_date,
                        "journal": "Zenodo",
                        "doi": doi or None,
                        "citation_count": 0,
                        "pdf_url": None,
                        "url": self_html or (f"https://doi.org/{doi}" if doi else None),
                        "metadata": {
                            "resource_type": resource_type,
                            "keywords": keywords,
                            "license": license_id,
                        },
                    })
            except Exception as e:
                logger.error("[Zenodo] %s: %s", type(e).__name__, e, exc_info=True)
        return papers
