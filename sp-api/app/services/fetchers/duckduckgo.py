"""DuckDuckGo 数据源 Fetcher

通用 web 兜底 — 用 `duckduckgo-search` Python 库（轻量，无 chromium，
HTML 解析在库内做）。

Inspired by: LDR `search_engine_ddg.py`（langchain_community wrapper）
ScholarPilot 改动：直接 `ddgs.text(...)`，不走 langchain；库未装时该源
fallback 到空 list（不破坏整轮检索）。

依赖：`pip install duckduckgo-search>=6.0`（参见 sp-api/requirements.txt）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)


class DuckDuckGoFetcher(AbstractFetcher):
    source_id = "duckduckgo"
    DEFAULT_TIMEOUT = 25.0

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError:
            logger.info("[DuckDuckGo] duckduckgo-search 库未装，跳过该源")
            return []

        # ddgs 是同步 API；放到 thread 跑避免阻塞 event loop
        def _sync_search() -> List[Dict]:
            try:
                with DDGS() as ddgs:
                    return list(ddgs.text(
                        query,
                        max_results=min(max_results, 30),
                        safesearch="moderate",
                        region=("cn-zh" if (language or "").startswith("zh") else "us-en"),
                    ))
            except Exception as e:
                logger.warning("[DuckDuckGo] ddgs.text error: %s", e)
                return []

        try:
            raw_results = await asyncio.to_thread(_sync_search)
        except Exception as e:
            logger.error("[DuckDuckGo] thread error: %s", e)
            return []

        papers: List[Dict] = []
        for item in raw_results[:max_results]:
            title = item.get("title") or ""
            url = item.get("href") or item.get("link") or ""
            snippet = item.get("body") or item.get("snippet") or ""
            papers.append({
                "source": "duckduckgo",
                "external_id": url,
                "doc_type": "web_page",
                "title": title,
                "authors": "",
                "abstract": snippet,
                "publication_date": None,
                "journal": None,
                "doi": None,
                "citation_count": 0,
                "pdf_url": None,
                "url": url,
            })
        return papers
