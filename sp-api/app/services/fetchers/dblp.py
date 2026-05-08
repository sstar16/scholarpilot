"""
DBLP 计算机科学论文数据源
专注于 CS 顶级会议和期刊（CVPR/NeurIPS/ACL/ICML 等）
免费 JSON API，无需鉴权
"""
import logging
from typing import Dict, List, Optional
import httpx
from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

DBLP_SEARCH_URL = "https://dblp.org/search/publ/api"


class DBLPFetcher(AbstractFetcher):
    source_id = "dblp"
    DEFAULT_TIMEOUT = 20.0

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        papers = []
        params = {
            "q": query,
            "format": "json",
            "h": min(max_results * 3, 200),  # 多取一些，因为要按年份过滤
            "c": 0,
        }

        async with self._http_client() as client:
            try:
                r = await client.get(
                    DBLP_SEARCH_URL,
                    params=params,
                    headers={"Accept": "application/json"},
                )
                if r.status_code != 200:
                    logger.error("[DBLP] HTTP %d: %s", r.status_code, r.text[:200])
                    return []

                hits = r.json().get("result", {}).get("hits", {}).get("hit", [])
                if not hits:
                    logger.debug("[DBLP] 查询 '%s' 无结果", query[:60])
                    return []

                logger.debug("[DBLP] 查询 '%s' 原始命中 %d 条", query[:60], len(hits))

                for hit in hits:
                    if len(papers) >= max_results:
                        break
                    info = hit.get("info", {})
                    year_str = info.get("year", "")
                    year = int(year_str) if year_str and year_str.isdigit() else 0

                    # 年份过滤
                    if year_from and year and year < year_from:
                        continue
                    if year_to and year and year > year_to:
                        continue

                    # 作者解析（DBLP 单作者时是 dict，多作者时是 list）
                    authors_raw = info.get("authors", {}).get("author", [])
                    if isinstance(authors_raw, dict):
                        authors_raw = [authors_raw]
                    authors_names = [
                        (a.get("text") or a) if isinstance(a, dict) else str(a)
                        for a in authors_raw[:5]
                    ]
                    authors = ", ".join(authors_names)
                    if len(authors_raw) > 5:
                        authors += " et al."

                    key = info.get("key", hit.get("@id", ""))
                    ee = info.get("ee", "")
                    # ee 有时是 list（有 OA + paid 两条链接）
                    if isinstance(ee, list):
                        ee = ee[0] if ee else ""

                    # venue 在 proceedings 类论文是 list（如 ["MLIS", "Frontiers in AI..."]）
                    # backend documents.journal 是 VARCHAR，list 会触发 asyncpg DataError 整轮挂掉
                    venue = info.get("venue")
                    if isinstance(venue, list):
                        venue = ", ".join(str(v) for v in venue if v)

                    papers.append({
                        "source": "dblp",
                        "external_id": key,
                        "doc_type": "paper",
                        "title": (info.get("title") or "").rstrip("."),
                        "authors": authors,
                        "abstract": None,  # DBLP 不提供摘要
                        "publication_date": f"{year}-01-01" if year else None,
                        "journal": venue,
                        "doi": info.get("doi"),
                        "citation_count": 0,
                        "url": ee or info.get("url", f"https://dblp.org/rec/{key}"),
                        "pdf_url": None,
                    })

                logger.debug("[DBLP] 过滤后返回 %d 篇", len(papers))

            except Exception as e:
                logger.error("[DBLP] %s: %s", type(e).__name__, e, exc_info=True)

        return papers[:max_results]
