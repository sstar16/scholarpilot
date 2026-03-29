"""
专利数据源 Fetcher
USPTO PatentsView API — 免费，无需 API key
"""
import traceback
from typing import Dict, List, Optional
import httpx
from app.services.fetchers.base import AbstractFetcher

PATENTSVIEW_BASE = "https://api.patentsview.org/patents/query"


class USPTOFetcher(AbstractFetcher):
    source_id = "uspto"
    DEFAULT_TIMEOUT = 20.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []

        # 构建 PatentsView 查询：标题 + 摘要 双路搜索
        criteria = [{"_or": [
            {"_text_any": {"patent_title": query}},
            {"_text_any": {"patent_abstract": query}},
        ]}]
        if year_from:
            criteria.append({"_gte": {"patent_date": f"{year_from}-01-01"}})
        if year_to:
            criteria.append({"_lte": {"patent_date": f"{year_to}-12-31"}})

        if len(criteria) == 1:
            q = criteria[0]
        else:
            q = {"_and": criteria}

        payload = {
            "q": q,
            "f": [
                "patent_number", "patent_title", "patent_abstract",
                "patent_date", "patent_num_cited_by_us_patents",
                "assignee_organization", "inventor_first_name", "inventor_last_name"
            ],
            "o": {"page": 1, "per_page": min(max_results, 100)},
            "s": [{"patent_num_cited_by_us_patents": "desc"}],
        }

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            try:
                r = await client.post(PATENTSVIEW_BASE, json=payload)
                if r.status_code == 200:
                    data = r.json()
                    for patent in (data.get("patents") or []):
                        # 提取发明人
                        inventors = patent.get("inventors") or []
                        authors = ", ".join([
                            f"{inv.get('inventor_first_name', '')} {inv.get('inventor_last_name', '')}".strip()
                            for inv in inventors[:5]
                        ])
                        if len(inventors) > 5:
                            authors += " et al."

                        # 提取申请人
                        assignees = patent.get("assignees") or []
                        journal = ", ".join([
                            a.get("assignee_organization", "") for a in assignees[:3] if a.get("assignee_organization")
                        ]) or "USPTO"

                        patent_num = patent.get("patent_number", "")
                        papers.append({
                            "source": "uspto",
                            "external_id": patent_num,
                            "doc_type": "patent",
                            "title": patent.get("patent_title", ""),
                            "authors": authors,
                            "abstract": patent.get("patent_abstract"),
                            "publication_date": patent.get("patent_date"),
                            "journal": journal,
                            "doi": None,
                            "citation_count": patent.get("patent_num_cited_by_us_patents", 0) or 0,
                            "pdf_url": None,
                            "url": f"https://patents.google.com/patent/US{patent_num}" if patent_num else None,
                        })
                else:
                    print(f"[USPTO] HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                print(f"[USPTO] {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return papers[:max_results]
