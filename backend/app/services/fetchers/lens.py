"""
Lens.org 专利 Fetcher (API v2)
覆盖范围：CN / US / EP / WO / JP / KR 等 90+ 国家，1.6亿+ 专利
申请 token：https://www.lens.org/lens/user/subscriptions → Patent API → Trial Access
"""
import logging
from typing import Dict, List
import httpx
from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

LENS_API_URL = "https://api.lens.org/patent/search"

JURISDICTION_LABELS = {
    "CN": "中国专利", "US": "美国专利", "EP": "欧洲专利",
    "WO": "PCT国际专利", "JP": "日本专利", "KR": "韩国专利",
}


class LensPatentFetcher(AbstractFetcher):
    source_id = "lens_patent"
    DEFAULT_TIMEOUT = 25.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        from app.config import settings
        token = getattr(settings, "lens_api_token", "").strip()
        if not token:
            logger.warning("[Lens] LENS_API_TOKEN 未配置，跳过专利检索")
            return []

        # Lens v2: query_string 搜索全文字段（标题+摘要+权利要求）
        bool_query: dict = {
            "must": [{"query_string": {"query": query}}],
            "filter": [
                {"terms": {"jurisdiction": ["CN", "US", "EP", "WO", "JP", "KR"]}}
            ],
        }

        if year_from:
            bool_query["filter"].append({"range": {"date_published": {"gte": f"{year_from}-01-01"}}})
        if year_to:
            bool_query["filter"].append({"range": {"date_published": {"lte": f"{year_to}-12-31"}}})

        payload = {
            "query": {"bool": bool_query},
            "size": min(max_results, 100),
            "sort": [{"relevance": "desc"}],
            "include": ["lens_id", "jurisdiction", "date_published", "biblio", "doc_key"],
        }

        papers = []
        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            try:
                r = await client.post(
                    LENS_API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    logger.info("[Lens] 检索到 %d 条专利 (总计 %d)", len(data.get("data", [])), data.get("total", 0))

                    for item in data.get("data", []):
                        lens_id = item.get("lens_id", "")
                        jurisdiction = item.get("jurisdiction", "")
                        biblio = item.get("biblio", {})

                        # 标题：biblio.invention_title[0].text
                        titles = biblio.get("invention_title", [])
                        title = titles[0].get("text", "") if titles else ""

                        # 摘要：biblio.abstract (可能是 list 或 dict)
                        abstract = ""
                        raw_abstract = biblio.get("abstract")
                        if isinstance(raw_abstract, list) and raw_abstract:
                            abstract = raw_abstract[0].get("text", "") if isinstance(raw_abstract[0], dict) else str(raw_abstract[0])
                        elif isinstance(raw_abstract, dict):
                            abstract = raw_abstract.get("text", "")
                        elif isinstance(raw_abstract, str):
                            abstract = raw_abstract

                        # 申请人：biblio.parties.applicants
                        parties = biblio.get("parties", {})
                        applicants = parties.get("applicants", [])
                        assignee = ", ".join(
                            a.get("extracted_name", {}).get("value", "")
                            for a in applicants[:3]
                            if a.get("extracted_name", {}).get("value")
                        ) or JURISDICTION_LABELS.get(jurisdiction, "专利")

                        # 发明人：biblio.parties.inventors
                        inventors = parties.get("inventors", [])
                        authors = ", ".join(
                            inv.get("extracted_name", {}).get("value", "")
                            for inv in inventors[:5]
                            if inv.get("extracted_name", {}).get("value")
                        )
                        if len(inventors) > 5:
                            authors += " et al."

                        # 被引数：biblio.cited_by.patent_count 或 references_cited.patent_count
                        cited_by = biblio.get("cited_by", {})
                        citation_count = cited_by.get("patent_count", 0) if isinstance(cited_by, dict) else 0

                        # 链接
                        url = f"https://www.lens.org/lens/patent/{lens_id}" if lens_id else None

                        papers.append({
                            "source": "lens_patent",
                            "external_id": lens_id,
                            "doc_type": "patent",
                            "title": title,
                            "authors": authors,
                            "abstract": abstract,
                            "publication_date": item.get("date_published"),
                            "journal": f"{JURISDICTION_LABELS.get(jurisdiction, jurisdiction)} — {assignee}",
                            "doi": None,
                            "citation_count": citation_count,
                            "pdf_url": None,
                            "url": url,
                        })
                elif r.status_code == 401:
                    logger.error("[Lens] 401 Unauthorized：LENS_API_TOKEN 无效或已过期")
                elif r.status_code == 429:
                    logger.error("[Lens] 429 Rate limited：免费额度已用完")
                else:
                    logger.error("[Lens] HTTP %d: %s", r.status_code, r.text[:300])
            except Exception as e:
                logger.error("[Lens] %s: %s", type(e).__name__, e, exc_info=True)

        return papers[:max_results]
