"""Wikipedia 数据源 Fetcher

REST API：`https://{lang}.wikipedia.org/w/api.php`
- list=search + prop=extracts 一次拿到摘要 + URL
- doc_type='encyclopedia'，定位"项目早期画像 / 术语澄清 / 背景知识"

Inspired by: LDR `search_engine_wikipedia.py`（用 `wikipedia` PyPI 库 + 两阶段）
ScholarPilot 改动：直 REST API（不依赖 wikipedia 库），无 LLM 二阶段（评分由
ScoringAgent 统一做），httpx 直 GET（与基类 `_http_client` 复用连接池）。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)


def _wikipedia_endpoint(language: Optional[str]) -> str:
    """根据 language 选择中/英维基。其他语言落到 en（避免无效查询）。"""
    if language and language.lower().startswith("zh"):
        return "https://zh.wikipedia.org/w/api.php"
    return "https://en.wikipedia.org/w/api.php"


class WikipediaFetcher(AbstractFetcher):
    source_id = "wikipedia"
    DEFAULT_TIMEOUT = 15.0

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        endpoint = _wikipedia_endpoint(language)
        # 第一步：list=search 拿 pageid + title + snippet
        # 第二步：prop=extracts|info 拿摘要 + URL（合并到一次请求）
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": min(max_results, 50),
            "srprop": "snippet|titlesnippet",
            "utf8": 1,
        }
        papers: List[Dict] = []
        async with self._http_client(headers={"User-Agent": "ScholarPilot/2.0 (scholarpilot@example.com)"}) as client:
            try:
                r = await client.get(endpoint, params=params)
                if r.status_code != 200:
                    logger.warning("[Wikipedia] HTTP %d", r.status_code)
                    return []
                hits = (r.json() or {}).get("query", {}).get("search", []) or []
                if not hits:
                    return []
                # 拉摘要：批量调 extracts
                pageids = [str(h.get("pageid")) for h in hits if h.get("pageid")]
                extracts: Dict[str, str] = {}
                if pageids:
                    er = await client.get(endpoint, params={
                        "action": "query",
                        "format": "json",
                        "prop": "extracts|info",
                        "explaintext": 1,
                        "exintro": 1,
                        "exlimit": "max",
                        "inprop": "url",
                        "pageids": "|".join(pageids[:50]),
                        "utf8": 1,
                    })
                    if er.status_code == 200:
                        pages = (er.json() or {}).get("query", {}).get("pages", {}) or {}
                        for pid, info in pages.items():
                            extracts[str(pid)] = info.get("extract") or ""

                for hit in hits[:max_results]:
                    pid = str(hit.get("pageid", ""))
                    title = hit.get("title") or ""
                    snippet = (hit.get("snippet") or "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
                    abstract = extracts.get(pid) or snippet
                    # URL：维基提供 canonical URL，直接拼 wiki/Title 即可
                    base = endpoint.replace("/w/api.php", "/wiki/")
                    url = base + (title.replace(" ", "_") if title else "")
                    papers.append({
                        "source": "wikipedia",
                        "external_id": f"wiki:{pid}",
                        "doc_type": "encyclopedia",
                        "title": title,
                        "authors": "Wikipedia Contributors",
                        "abstract": abstract,
                        "publication_date": None,
                        "journal": "Wikipedia",
                        "doi": None,
                        "citation_count": 0,
                        "pdf_url": None,
                        "url": url,
                    })
            except Exception as e:
                logger.error("[Wikipedia] %s: %s", type(e).__name__, e, exc_info=True)
        return papers
