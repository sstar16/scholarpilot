"""
Crossref 数据源 Fetcher
免费学术文献元数据 API，1.3亿+ 记录
polite 模式需 mailto 参数获得更高限额
"""
import traceback
from typing import Dict, List, Optional
import httpx
from app.services.fetchers.base import AbstractFetcher

CROSSREF_BASE = "https://api.crossref.org/works"


class CrossrefFetcher(AbstractFetcher):
    source_id = "crossref"
    DEFAULT_TIMEOUT = 15.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []
        params = {
            "query": query,
            "rows": min(max_results, 100),
            "sort": "relevance",
            "order": "desc",
            "select": "DOI,title,author,abstract,published-print,published-online,"
                      "container-title,is-referenced-by-count,URL,type,link",
            "mailto": "scholarpilot@example.com",  # polite 模式
        }

        # 年份过滤
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}")
        if year_to:
            filters.append(f"until-pub-date:{year_to}")
        if filters:
            params["filter"] = ",".join(filters)

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            try:
                r = await client.get(CROSSREF_BASE, params=params)
                if r.status_code == 200:
                    data = r.json()
                    for item in (data.get("message", {}).get("items") or []):
                        # 标题
                        title_list = item.get("title", [])
                        title = title_list[0] if title_list else ""

                        # 作者
                        author_list = item.get("author", [])
                        authors = ", ".join([
                            f"{a.get('given', '')} {a.get('family', '')}".strip()
                            for a in author_list[:5]
                        ])
                        if len(author_list) > 5:
                            authors += " et al."

                        # 摘要（Crossref 的 abstract 可能是 JATS XML）
                        abstract = item.get("abstract", "")
                        if abstract:
                            import re
                            abstract = re.sub(r'<[^>]+>', '', abstract).strip()

                        # 出版日期
                        date_parts = (
                            item.get("published-print", {}).get("date-parts", [[]])
                            or item.get("published-online", {}).get("date-parts", [[]])
                        )
                        pub_date = None
                        if date_parts and date_parts[0]:
                            parts = date_parts[0]
                            pub_date = "-".join(str(p).zfill(2) for p in parts[:3])

                        # 期刊
                        container = item.get("container-title", [])
                        journal = container[0] if container else None

                        # PDF URL
                        pdf_url = None
                        for link in (item.get("link") or []):
                            if link.get("content-type") == "application/pdf":
                                pdf_url = link.get("URL")
                                break

                        doi = item.get("DOI", "")
                        papers.append({
                            "source": "crossref",
                            "external_id": doi,
                            "doc_type": "paper",
                            "title": title,
                            "authors": authors,
                            "abstract": abstract,
                            "publication_date": pub_date,
                            "journal": journal,
                            "doi": doi,
                            "citation_count": item.get("is-referenced-by-count", 0) or 0,
                            "pdf_url": pdf_url,
                            "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
                        })
                else:
                    print(f"[Crossref] HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                print(f"[Crossref] {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return papers[:max_results]
