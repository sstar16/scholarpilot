"""
国际学术数据源 Fetcher (sp-api 版本)
继承 v1 enhanced_data_fetcher.py 的抓取逻辑，重构为 AbstractFetcher 子类

vs backend/app/services/fetchers/international.py 差异：
- ALL_FETCHERS 不含 BigQueryPatentsFetcher（sp-api 不装 google-cloud-bigquery）
- ALL_FETCHERS 不含 local_kb（sp-api 没 knowledge_base 模块）
- types.py 同步移除 bigquery_patents / local_kb 引用
"""
import asyncio
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)


PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_BASE = "https://api.openalex.org"
SEMANTIC_BASE = "https://api.semanticscholar.org/graph/v1"
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ARXIV_BASE = "https://export.arxiv.org/api"
BIORXIV_BASE = "https://api.biorxiv.org/details/biorxiv"
MEDRXIV_BASE = "https://api.biorxiv.org/details/medrxiv"


class PubMedFetcher(AbstractFetcher):
    source_id = "pubmed"
    DEFAULT_TIMEOUT = 20.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        term = query
        if year_from:
            term += f" AND {year_from}:{year_to or datetime.now().year}[pdat]"

        articles = []
        pmid_to_article: Dict[str, Dict] = {}

        async with self._http_client() as client:
            try:
                r = await client.get(f"{PUBMED_BASE}/esearch.fcgi", params={
                    "db": "pubmed", "term": term, "retmax": max_results,
                    "retmode": "json", "sort": "relevance"
                })
                if r.status_code != 200:
                    return []
                id_list = r.json().get("esearchresult", {}).get("idlist", [])
                if not id_list:
                    return []

                for i in range(0, len(id_list), 50):
                    batch = id_list[i:i+50]
                    sr = await client.get(f"{PUBMED_BASE}/esummary.fcgi", params={
                        "db": "pubmed", "id": ",".join(batch), "retmode": "json"
                    })
                    if sr.status_code == 200:
                        results = sr.json().get("result", {})
                        for pmid in batch:
                            if pmid in results and pmid != "uids" and isinstance(results[pmid], dict):
                                art = results[pmid]
                                authors_list = art.get("authors", [])
                                authors = ", ".join([a.get("name", "") for a in authors_list[:5]])
                                if len(authors_list) > 5:
                                    authors += " et al."
                                doc = {
                                    "source": "pubmed",
                                    "external_id": pmid,
                                    "doc_type": "paper",
                                    "title": art.get("title", ""),
                                    "authors": authors,
                                    "journal": art.get("fulljournalname") or art.get("source", ""),
                                    "publication_date": art.get("pubdate", ""),
                                    "doi": next((aid.get("value") for aid in art.get("articleids", []) if aid.get("idtype") == "doi"), None),
                                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                                    "abstract": None,
                                    "citation_count": 0,
                                }
                                articles.append(doc)
                                pmid_to_article[pmid] = doc
                    await asyncio.sleep(0.3)

                for i in range(0, len(id_list), 50):
                    batch = id_list[i:i+50]
                    er = await client.get(f"{PUBMED_BASE}/efetch.fcgi", params={
                        "db": "pubmed", "id": ",".join(batch),
                        "rettype": "xml", "retmode": "xml"
                    })
                    if er.status_code == 200:
                        try:
                            root = ET.fromstring(er.text)
                            for pa in root.findall(".//PubmedArticle"):
                                pmid_elem = pa.find(".//PMID")
                                if pmid_elem is None:
                                    continue
                                pmid = pmid_elem.text
                                abstract_parts = [
                                    elem.text for elem in pa.findall(".//AbstractText")
                                    if elem.text
                                ]
                                if abstract_parts and pmid in pmid_to_article:
                                    pmid_to_article[pmid]["abstract"] = " ".join(abstract_parts)
                        except ET.ParseError:
                            pass
                    await asyncio.sleep(0.3)

            except Exception as e:
                logger.error("[PubMed] %s: %s", type(e).__name__, e, exc_info=True)
        return articles[:max_results]


class OpenAlexFetcher(AbstractFetcher):
    source_id = "openalex"
    DEFAULT_TIMEOUT = 15.0

    _SELECT_FIELDS = (
        "id,doi,title,authorships,cited_by_count,publication_date,"
        "primary_location,open_access,abstract_inverted_index,language"
    )

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []
        params = {
            "search": query,
            "per_page": min(max_results, 200),
            "mailto": "scholarpilot@example.com",
            "select": self._SELECT_FIELDS,
        }
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if language == "zh":
            filters.append("language:zh")
        if filters:
            params["filter"] = ",".join(filters)

        async with self._http_client() as client:
            try:
                r = await client.get(f"{OPENALEX_BASE}/works", params=params)
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    for work in results:
                        authorships = work.get("authorships", [])
                        authors = ", ".join([a.get("author", {}).get("display_name", "") for a in authorships[:5]])
                        if len(authorships) > 5:
                            authors += " et al."
                        countries = []
                        seen_cc = set()
                        for a in authorships:
                            for inst in a.get("institutions", []):
                                cc = inst.get("country_code")
                                if cc and cc not in seen_cc:
                                    countries.append(cc.upper())
                                    seen_cc.add(cc)
                        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))
                        papers.append({
                            "source": "openalex",
                            "external_id": work.get("id", ""),
                            "doc_type": "paper",
                            "title": work.get("title", ""),
                            "authors": authors,
                            "abstract": abstract,
                            "publication_date": work.get("publication_date"),
                            "journal": ((work.get("primary_location") or {}).get("source") or {}).get("display_name"),
                            "doi": work.get("doi"),
                            "url": work.get("id"),
                            "citation_count": work.get("cited_by_count", 0),
                            "pdf_url": (work.get("primary_location") or {}).get("pdf_url") if work.get("primary_location") else None,
                            "countries": countries or None,
                        })
                else:
                    logger.warning("[OpenAlex] HTTP %d，params=%s", r.status_code, params)
            except Exception as e:
                logger.error("[OpenAlex] %s: %s", type(e).__name__, e, exc_info=True)
        return papers[:max_results]

    def _reconstruct_abstract(self, inverted_index: Optional[Dict]) -> Optional[str]:
        if not inverted_index:
            return None
        try:
            word_positions = []
            for word, positions in inverted_index.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort(key=lambda x: x[0])
            return " ".join(w for _, w in word_positions)
        except Exception:
            return None


class OpenAlexZhFetcher(OpenAlexFetcher):
    """OpenAlex 中文论文专用 — 双策略合并。"""
    DEFAULT_TIMEOUT = 25.0
    source_id = "openalex_zh"

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        import asyncio as _aio

        if "|||" in query:
            zh_query, en_query = query.split("|||", 1)
            zh_query = zh_query.strip()
            en_query = en_query.strip()
        else:
            zh_query = self._limit_terms(query, 3)
            en_words = [w for w in query.split() if not self._is_chinese(w)]
            en_query = " ".join(en_words[:5]) if en_words else query

        async def _empty():
            return []

        task_a = super().fetch(zh_query, max_results, year_from, year_to, language="zh") if zh_query else _empty()
        task_b = self._fetch_cn_institutions(en_query, max_results, year_from, year_to) if en_query else _empty()

        results_a, results_b = await _aio.gather(task_a, task_b, return_exceptions=True)

        seen = set()
        merged = []
        for batch in [results_a, results_b]:
            if isinstance(batch, Exception):
                continue
            for doc in batch:
                doc["source"] = "openalex_zh"
                key = doc.get("external_id") or doc.get("title", "")
                if key not in seen:
                    seen.add(key)
                    merged.append(doc)

        return merged[:max_results]

    async def _fetch_cn_institutions(self, query: str, max_results, year_from, year_to) -> List[Dict]:
        params = {
            "search": query,
            "per_page": min(max_results, 200),
            "mailto": "scholarpilot@example.com",
            "select": self._SELECT_FIELDS,
        }
        filters = ["institutions.country_code:cn"]
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        params["filter"] = ",".join(filters)

        async with self._http_client() as client:
            try:
                r = await client.get(f"{OPENALEX_BASE}/works", params=params)
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    papers = []
                    for work in results:
                        authorships = work.get("authorships", [])
                        authors = ", ".join([a.get("author", {}).get("display_name", "") for a in authorships[:5]])
                        if len(authorships) > 5:
                            authors += " et al."
                        countries = []
                        seen_cc = set()
                        for a in authorships:
                            for inst in a.get("institutions", []):
                                cc = inst.get("country_code")
                                if cc and cc not in seen_cc:
                                    countries.append(cc.upper())
                                    seen_cc.add(cc)
                        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))
                        papers.append({
                            "source": "openalex_zh",
                            "external_id": work.get("id", ""),
                            "doc_type": "paper",
                            "title": work.get("title", ""),
                            "authors": authors,
                            "abstract": abstract,
                            "publication_date": work.get("publication_date"),
                            "journal": ((work.get("primary_location") or {}).get("source") or {}).get("display_name"),
                            "doi": work.get("doi"),
                            "url": work.get("id"),
                            "citation_count": work.get("cited_by_count", 0),
                            "pdf_url": (work.get("primary_location") or {}).get("pdf_url") if work.get("primary_location") else None,
                            "countries": countries or None,
                        })
                    return papers[:max_results]
            except Exception as e:
                logger.warning("[OpenAlex_zh] country_code:cn 策略失败: %s", e)
        return []

    @staticmethod
    def _limit_terms(query: str, n: int) -> str:
        import re as _re
        cn_terms = _re.findall(r'[一-鿿]+', query)
        if cn_terms:
            return " ".join(cn_terms[:n])
        words = query.split()
        return " ".join(words[:n])

    @staticmethod
    def _is_chinese(text: str) -> bool:
        import re as _re
        return bool(_re.search(r'[一-鿿]', text))


class SemanticScholarFetcher(AbstractFetcher):
    source_id = "semantic_scholar"
    DEFAULT_TIMEOUT = 20.0

    def _get_api_key(self) -> str:
        return os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []
        params: dict = {
            "query": query,
            "limit": min(max_results, 1000),
            "fields": "paperId,title,abstract,authors,year,citationCount,venue,publicationDate,openAccessPdf,externalIds,journal",
        }
        if year_from and year_to:
            params["year"] = f"{year_from}-{year_to}"
        elif year_from:
            params["year"] = f"{year_from}-"

        headers: dict = {"Accept": "application/json"}
        api_key = self._get_api_key()
        if api_key:
            headers["x-api-key"] = api_key

        async with self._http_client() as client:
            try:
                for attempt in range(3):
                    r = await client.get(
                        f"{SEMANTIC_BASE}/paper/search/bulk",
                        params=params, headers=headers,
                    )
                    if r.status_code == 200:
                        for paper in r.json().get("data", []):
                            authors = ", ".join([a.get("name", "") for a in paper.get("authors", [])[:5]])
                            if len(paper.get("authors", [])) > 5:
                                authors += " et al."
                            ext = paper.get("externalIds", {})
                            papers.append({
                                "source": "semantic_scholar",
                                "external_id": paper.get("paperId", ""),
                                "doc_type": "paper",
                                "title": paper.get("title", ""),
                                "authors": authors,
                                "abstract": paper.get("abstract"),
                                "publication_date": paper.get("publicationDate"),
                                "journal": (paper.get("journal") or {}).get("name") if paper.get("journal") else paper.get("venue"),
                                "doi": ext.get("DOI"),
                                "citation_count": paper.get("citationCount", 0),
                                "pdf_url": (paper.get("openAccessPdf") or {}).get("url") if paper.get("openAccessPdf") else None,
                                "url": f"https://www.semanticscholar.org/paper/{paper.get('paperId')}",
                            })
                        break
                    elif r.status_code == 429:
                        delay = int(r.headers.get("Retry-After", 0)) or min(2 ** (attempt + 1), 30)
                        await asyncio.sleep(delay)
                    else:
                        break
            except Exception as e:
                logger.error("[SemanticScholar] %s: %s", type(e).__name__, e, exc_info=True)
        return papers[:max_results]


class EuropePMCFetcher(AbstractFetcher):
    source_id = "europe_pmc"
    DEFAULT_TIMEOUT = 15.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []
        q = query
        if year_from:
            q += f" AND (FIRST_PDATE:[{year_from}-01-01 TO {year_to or datetime.now().year}-12-31])"

        async with self._http_client() as client:
            try:
                r = await client.get(f"{EUROPE_PMC_BASE}/search", params={
                    "query": q, "format": "json",
                    "pageSize": min(max_results, 100), "resultType": "core"
                })
                if r.status_code == 200:
                    for item in r.json().get("resultList", {}).get("result", []):
                        author_list = item.get("authorList", {}).get("author", [])
                        authors = ", ".join([f"{a.get('firstName','')} {a.get('lastName','')}".strip() for a in author_list[:5]])
                        if len(author_list) > 5:
                            authors += " et al."
                        papers.append({
                            "source": "europe_pmc",
                            "external_id": item.get("pmid") or item.get("doi") or item.get("id", ""),
                            "doc_type": "paper",
                            "title": item.get("title", ""),
                            "authors": authors,
                            "abstract": item.get("abstractText"),
                            "publication_date": item.get("firstPublicationDate"),
                            "journal": item.get("journalTitle"),
                            "doi": item.get("doi"),
                            "citation_count": item.get("citedByCount", 0),
                            "url": f"https://europepmc.org/article/MED/{item.get('pmid')}" if item.get("pmid") else None,
                        })
            except Exception as e:
                logger.error("[EuropePMC] %s: %s", type(e).__name__, e, exc_info=True)
        return papers[:max_results]


class ArXivFetcher(AbstractFetcher):
    source_id = "arxiv"
    DEFAULT_TIMEOUT = 20.0

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []
        search_query = f"all:{query}"
        params = {
            "search_query": search_query,
            "max_results": min(max_results, 100),
            "sortBy": "relevance",
        }
        async with self._http_client(headers={"User-Agent": "ScholarPilot/2.0 (scholarpilot@example.com)"}) as client:
            try:
                r = await client.get(f"{ARXIV_BASE}/query", params=params)
                if r.status_code == 200:
                    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
                    root = ET.fromstring(r.text)
                    for entry in root.findall("atom:entry", ns):
                        pub_date = entry.findtext("atom:published", "", ns)[:10]
                        if year_from and pub_date and int(pub_date[:4]) < year_from:
                            continue
                        arxiv_id = entry.findtext("atom:id", "", ns).split("/abs/")[-1]
                        authors = ", ".join([
                            a.findtext("atom:name", "", ns)
                            for a in entry.findall("atom:author", ns)[:5]
                        ])
                        papers.append({
                            "source": "arxiv",
                            "external_id": arxiv_id,
                            "doc_type": "preprint",
                            "title": entry.findtext("atom:title", "", ns).strip(),
                            "authors": authors,
                            "abstract": entry.findtext("atom:summary", "", ns).strip(),
                            "publication_date": pub_date,
                            "journal": "arXiv",
                            "doi": None,
                            "citation_count": 0,
                            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                            "url": f"https://arxiv.org/abs/{arxiv_id}",
                        })
            except Exception as e:
                logger.error("[arXiv] %s: %s", type(e).__name__, e, exc_info=True)
        return papers[:max_results]


class BioRxivFetcher(AbstractFetcher):
    source_id = "biorxiv"
    DEFAULT_TIMEOUT = 20.0
    _server = "biorxiv"

    async def fetch(self, query: str, max_results=20, year_from=None, year_to=None, language=None) -> List[Dict]:
        papers = []
        end_date = datetime.now().strftime("%Y-%m-%d")
        if year_from:
            start_date = f"{year_from}-01-01"
        else:
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

        base_url = BIORXIV_BASE if self._server == "biorxiv" else MEDRXIV_BASE
        search_words = [w for w in query.lower().split() if len(w) > 2]

        async with self._http_client(headers={"User-Agent": "ScholarPilot/2.0 (scholarpilot@example.com)"}) as client:
            try:
                cursor = 0
                for _ in range(3):
                    if len(papers) >= max_results:
                        break
                    r = await client.get(f"{base_url}/{start_date}/{end_date}/{cursor}")
                    if r.status_code != 200:
                        break
                    collection = r.json().get("collection", [])
                    if not collection:
                        break
                    for p in collection:
                        title_l = (p.get("title") or "").lower()
                        abstract_l = (p.get("abstract") or "").lower()
                        if any(w in title_l or w in abstract_l for w in search_words):
                            papers.append({
                                "source": self._server,
                                "external_id": p.get("doi") or "",
                                "doc_type": "preprint",
                                "title": p.get("title", ""),
                                "authors": p.get("authors", ""),
                                "abstract": p.get("abstract"),
                                "publication_date": p.get("date"),
                                "journal": self._server,
                                "doi": p.get("doi"),
                                "citation_count": 0,
                                "pdf_url": f"https://www.{self._server}.org/content/{p.get('doi')}.full.pdf" if p.get("doi") else None,
                                "url": f"https://www.{self._server}.org/content/{p.get('doi')}" if p.get("doi") else None,
                            })
                    cursor += len(collection)
                    if len(collection) < 100:
                        break
                    await asyncio.sleep(1.0)
            except Exception as e:
                logger.error("[%s] %s: %s", self._server, type(e).__name__, e, exc_info=True)
        return papers[:max_results]


class MedRxivFetcher(BioRxivFetcher):
    source_id = "medrxiv"
    _server = "medrxiv"


# ── 引入其他 fetcher 文件 ────────────────────────────────────
from app.services.fetchers.patents import USPTOFetcher
from app.services.fetchers.clinical import ClinicalTrialsFetcher
from app.services.fetchers.crossref import CrossrefFetcher
from app.services.fetchers.lens import LensPatentFetcher
from app.services.fetchers.dblp import DBLPFetcher
from app.services.fetchers.epo import EPOFetcher
from app.services.fetchers.patenthub import PatentHubFetcher
# ── 2026-05-08 LDR-inspired 扩展 ────────────────────────────
from app.services.fetchers.wikipedia import WikipediaFetcher
from app.services.fetchers.tavily import TavilyFetcher
from app.services.fetchers.zenodo import ZenodoFetcher
from app.services.fetchers.duckduckgo import DuckDuckGoFetcher
from app.services.fetchers.github_search import GitHubFetcher
from app.services.fetchers.stackexchange import StackExchangeFetcher
from app.services.fetchers.types import SourceId, assert_registry_exhaustive

# ── 注册表（sp-api 13 个，不含 bigquery_patents / local_kb）────────────
ALL_FETCHERS: Dict[SourceId, AbstractFetcher] = {
    "pubmed": PubMedFetcher(),
    "openalex": OpenAlexFetcher(),
    "semantic_scholar": SemanticScholarFetcher(),
    "europe_pmc": EuropePMCFetcher(),
    "arxiv": ArXivFetcher(),
    "biorxiv": BioRxivFetcher(),
    "medrxiv": MedRxivFetcher(),
    "uspto": USPTOFetcher(),
    "lens_patent": LensPatentFetcher(),
    "clinical_trials": ClinicalTrialsFetcher(),
    "crossref": CrossrefFetcher(),
    "dblp": DBLPFetcher(),
    "openalex_zh": OpenAlexZhFetcher(),
    "epo_ops": EPOFetcher(),
    "patenthub": PatentHubFetcher(),
    # ── 2026-05-08 LDR-inspired 扩展 ─────────────────────────
    "wikipedia": WikipediaFetcher(),
    "tavily": TavilyFetcher(),
    "zenodo": ZenodoFetcher(),
    "duckduckgo": DuckDuckGoFetcher(),
    "github": GitHubFetcher(),
    "stackexchange": StackExchangeFetcher(),
}


assert_registry_exhaustive(ALL_FETCHERS)


# ── Paid PDF source helpers ───────────────────────────────────────────────


def get_paid_pdf_source_ids() -> List[str]:
    return [sid for sid, f in ALL_FETCHERS.items() if getattr(f, "PAID_PDF", False)]


def is_paid_pdf_source(source_id: Optional[str]) -> bool:
    if not source_id:
        return False
    f = ALL_FETCHERS.get(source_id)
    return bool(f and getattr(f, "PAID_PDF", False))
