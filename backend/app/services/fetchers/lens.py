"""
Lens.org 专利 Fetcher
覆盖范围：CN（中国）/ US（美国）/ EP（欧洲）/ WO（PCT国际）/ JP / KR 等 90+ 国家
免费账号：https://www.lens.org/lens/user/subscriptions → 申请 Scholarly API token
"""
import traceback
from typing import Dict, List
import httpx
from app.services.fetchers.base import AbstractFetcher

LENS_API_URL = "https://api.lens.org/patent/search"

JURISDICTION_LABELS = {
    "CN": "中国专利",
    "US": "美国专利",
    "EP": "欧洲专利",
    "WO": "PCT国际专利",
    "JP": "日本专利",
    "KR": "韩国专利",
}


class LensPatentFetcher(AbstractFetcher):
    source_id = "lens_patent"
    DEFAULT_TIMEOUT = 25.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        from app.config import settings
        token = getattr(settings, "lens_api_token", "").strip()
        if not token:
            return []  # 未配置 token，跳过

        # 构建 bool query：标题 + 摘要 + 权利要求 三路搜索
        must_clauses = [{
            "bool": {
                "should": [
                    {"match": {"title": query}},
                    {"match": {"abstract": query}},
                    {"match": {"claims.claims.claim_text": query}},
                ],
                "minimum_should_match": 1,
            }
        }]

        filters = [
            # 优先覆盖中美欧及PCT
            {"terms": {"jurisdiction": ["CN", "US", "EP", "WO", "JP", "KR"]}}
        ]
        if year_from:
            filters.append({"range": {"date_published": {"gte": f"{year_from}-01-01"}}})
        if year_to:
            filters.append({"range": {"date_published": {"lte": f"{year_to}-12-31"}}})

        payload = {
            "query": {
                "bool": {
                    "must": must_clauses,
                    "filter": filters,
                }
            },
            "size": min(max_results, 100),
            "sort": [{"_score": "desc"}],
            "include": [
                "lens_id", "title", "abstract", "date_published",
                "jurisdiction", "applicants", "inventors",
                "references_cited", "publication_type",
            ],
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
                    for item in r.json().get("data", []):
                        lens_id = item.get("lens_id", "")
                        jurisdiction = item.get("jurisdiction", "")

                        # 申请人（assignee）
                        applicants = item.get("applicants") or []
                        assignee = ", ".join(
                            a.get("name", "") for a in applicants[:3] if a.get("name")
                        ) or JURISDICTION_LABELS.get(jurisdiction, "专利")

                        # 发明人
                        inventors = item.get("inventors") or []
                        authors = ", ".join(
                            inv.get("name", "") for inv in inventors[:5] if inv.get("name")
                        )
                        if len(inventors) > 5:
                            authors += " et al."

                        # 引用数
                        citation_count = len((item.get("references_cited") or {}).get("patents") or [])

                        # 专利链接
                        url = f"https://www.lens.org/lens/patent/{lens_id}" if lens_id else None

                        papers.append({
                            "source": "lens_patent",
                            "external_id": lens_id,
                            "doc_type": "patent",
                            "title": item.get("title") or "",
                            "authors": authors,
                            "abstract": item.get("abstract"),
                            "publication_date": item.get("date_published"),
                            "journal": f"{JURISDICTION_LABELS.get(jurisdiction, jurisdiction)} — {assignee}",
                            "doi": None,
                            "citation_count": citation_count,
                            "pdf_url": None,
                            "url": url,
                        })
                elif r.status_code == 401:
                    print("[Lens] 401 Unauthorized：LENS_TOKEN 无效或已过期")
                elif r.status_code == 429:
                    print("[Lens] 429 Rate limited：免费额度已用完（10000次/月）")
                else:
                    print(f"[Lens] HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                print(f"[Lens] {type(e).__name__}: {e}\n{traceback.format_exc()}")

        return papers[:max_results]
