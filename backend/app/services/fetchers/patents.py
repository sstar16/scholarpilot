"""
专利数据源 Fetcher
USPTO PatentsView API v4 — 免费，需 API key

旧 API (api.patentsview.org) 已于 2024 年停用（HTTP 410）。
新 API 申请 key：https://patentsview.org/api/signup（免费，秒批）
配置方法：在 .env 中填写 PATENTSVIEW_API_KEY=xxx
"""
import logging
import os
from typing import Dict, List, Optional
import httpx
from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

PATENTSVIEW_BASE = "https://search.patentsview.org/api/v1/patent/"


class USPTOFetcher(AbstractFetcher):
    source_id = "uspto"
    DEFAULT_TIMEOUT = 20.0

    def __init__(self):
        self._api_key = os.getenv("PATENTSVIEW_API_KEY", "")

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        if not self._api_key:
            logger.warning("[USPTO] PATENTSVIEW_API_KEY 未配置，跳过。申请地址：https://patentsview.org/api/signup")
            return []

        papers = []

        # 构建 PatentsView v4 查询
        criteria = [{"_or": [
            {"_text_any": {"patent_title": query}},
            {"_text_any": {"patent_abstract": query}},
        ]}]
        if year_from:
            criteria.append({"_gte": {"patent_date": f"{year_from}-01-01"}})
        if year_to:
            criteria.append({"_lte": {"patent_date": f"{year_to}-12-31"}})

        q = criteria[0] if len(criteria) == 1 else {"_and": criteria}

        payload = {
            "q": q,
            "f": [
                "patent_id", "patent_title", "patent_abstract",
                "patent_date", "patent_num_us_patents_cited",
                "assignee_organization", "inventor_first_name", "inventor_last_name"
            ],
            "o": {"size": min(max_results, 100)},
            "s": [{"patent_date": "desc"}],
        }

        headers = {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
        }

        async with self._http_client() as client:
            try:
                r = await client.post(PATENTSVIEW_BASE, json=payload, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    for patent in (data.get("patents") or []):
                        inventors = patent.get("inventors") or []
                        authors = ", ".join([
                            f"{inv.get('inventor_first_name', '')} {inv.get('inventor_last_name', '')}".strip()
                            for inv in inventors[:5]
                        ])
                        if len(inventors) > 5:
                            authors += " et al."

                        assignees = patent.get("assignees") or []
                        journal = ", ".join([
                            a.get("assignee_organization", "") for a in assignees[:3]
                            if a.get("assignee_organization")
                        ]) or "USPTO"

                        patent_id = patent.get("patent_id", "")
                        papers.append({
                            "source": "uspto",
                            "external_id": patent_id,
                            "doc_type": "patent",
                            "title": patent.get("patent_title", ""),
                            "authors": authors,
                            "abstract": patent.get("patent_abstract"),
                            "publication_date": patent.get("patent_date"),
                            "journal": journal,
                            "doi": None,
                            "citation_count": patent.get("patent_num_us_patents_cited", 0) or 0,
                            "pdf_url": None,
                            "url": f"https://patents.google.com/patent/US{patent_id}" if patent_id else None,
                        })
                elif r.status_code == 401:
                    logger.error("[USPTO] 401 Unauthorized：PATENTSVIEW_API_KEY 无效，请重新申请")
                elif r.status_code == 410:
                    logger.error("[USPTO] 410 Gone：旧 PatentsView API 已停用，请使用 search.patentsview.org 新 API 并配置 PATENTSVIEW_API_KEY")
                else:
                    logger.error("[USPTO] HTTP %d: %s", r.status_code, r.text[:200])
            except Exception as e:
                logger.error("[USPTO] %s: %s", type(e).__name__, e, exc_info=True)
        return papers[:max_results]
