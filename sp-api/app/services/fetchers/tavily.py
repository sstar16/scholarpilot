"""Tavily 数据源 Fetcher

POST `https://api.tavily.com/search` — LLM-optimized web search。
- search_depth='basic'（更快，1 API call）；'advanced' 多消耗，更准
- 缺 TAVILY_API_KEY 时 fetcher 自动 disabled — safe_fetch 路径会拿到空 list
  并不报错（与 backend 现有 fetchers 失败容忍策略一致）

Inspired by: LDR `search_engine_tavily.py`（requests + langchain wrapper）
ScholarPilot 改动：httpx + 复用 `_http_client` 连接池；不依赖 langchain。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

TAVILY_ENDPOINT = "https://api.tavily.com/search"


class TavilyFetcher(AbstractFetcher):
    source_id = "tavily"
    DEFAULT_TIMEOUT = 25.0

    def _api_key(self) -> str:
        return os.getenv("TAVILY_API_KEY", "") or ""

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        api_key = self._api_key()
        if not api_key:
            logger.info("[Tavily] TAVILY_API_KEY 未配置，跳过该源")
            return []

        body = {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": min(max_results, 20),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        papers: List[Dict] = []
        async with self._http_client() as client:
            try:
                r = await client.post(TAVILY_ENDPOINT, json=body)
                if r.status_code != 200:
                    logger.warning("[Tavily] HTTP %d: %s", r.status_code, r.text[:200])
                    return []
                results = (r.json() or {}).get("results", []) or []
                for item in results[:max_results]:
                    title = item.get("title") or ""
                    url = item.get("url") or ""
                    snippet = item.get("content") or ""
                    score = item.get("score")
                    pub_date = item.get("published_date")  # Tavily 偶尔返回
                    papers.append({
                        "source": "tavily",
                        "external_id": url,  # Tavily 无独立 id，URL 当 id
                        "doc_type": "web_page",
                        "title": title,
                        "authors": "",
                        "abstract": snippet,
                        "publication_date": pub_date,
                        "journal": None,
                        "doi": None,
                        "citation_count": 0,
                        "pdf_url": None,
                        "url": url,
                        "metadata": {"tavily_score": score} if score is not None else None,
                    })
            except Exception as e:
                logger.error("[Tavily] %s: %s", type(e).__name__, e, exc_info=True)
        return papers
