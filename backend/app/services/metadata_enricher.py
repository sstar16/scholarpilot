"""
元数据补全链
对缺少摘要的文档，多源链式补全：
  EPO 专利 → EPO abstract endpoint → EPO description (前500字)
  学术论文 → OpenAlex (DOI) → Europe PMC (标题) → Crossref (标题)
"""
import asyncio
import logging
import os
import re
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

OPENALEX_WORKS = "https://api.openalex.org/works"
CROSSREF_WORKS = "https://api.crossref.org/works"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EPO_PUBLISHED = "https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc"
EPO_TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"

MAX_ENRICH_PER_ROUND = 30
ENRICH_TIMEOUT = 12.0


async def enrich_missing_abstracts(docs: List[Dict]) -> List[Dict]:
    """
    对缺少 abstract 的文档，多源链式补全。
    EPO 专利和学术论文走不同的补全链。
    """
    missing = [d for d in docs if not (d.get("abstract") or "").strip()]
    if not missing:
        return docs

    # 分类：专利 vs 论文
    patent_missing = [d for d in missing if d.get("source") == "epo_ops"]
    paper_missing = [d for d in missing if d.get("source") != "epo_ops"]
    # 专利优先，然后论文
    prioritized = patent_missing + paper_missing
    to_enrich = prioritized[:MAX_ENRICH_PER_ROUND]

    logger.info("[Enricher] %d 篇缺摘要（EPO %d / 论文 %d），尝试补全 %d 篇",
                len(missing), len(patent_missing), len(paper_missing), len(to_enrich))

    # 获取 EPO token（如果有专利要补全）
    epo_token = None
    if patent_missing:
        epo_token = await _get_epo_token()

    async with httpx.AsyncClient(timeout=ENRICH_TIMEOUT) as client:
        tasks = [_enrich_one(doc, client, epo_token) for doc in to_enrich]
        await asyncio.gather(*tasks, return_exceptions=True)

    enriched_count = sum(1 for d in to_enrich if (d.get("abstract") or "").strip())
    logger.info("[Enricher] 成功补全 %d/%d 篇摘要", enriched_count, len(to_enrich))

    return docs


async def _get_epo_token() -> Optional[str]:
    """获取 EPO OAuth2 token"""
    key = os.getenv("EPO_CONSUMER_KEY", "")
    secret = os.getenv("EPO_CONSUMER_SECRET", "")
    if not key or not secret:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                EPO_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(key, secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if r.status_code == 200:
                return r.json().get("access_token")
    except Exception as e:
        logger.debug("[Enricher] EPO token 获取失败: %s", e)
    return None


async def _enrich_one(doc: Dict, client: httpx.AsyncClient, epo_token: Optional[str] = None):
    """多源链式补全单篇文档"""
    source = doc.get("source", "")

    if source == "epo_ops":
        # EPO 专利补全链：EPO description → (无更多源)
        await _enrich_epo_patent(doc, client, epo_token)
    else:
        # 学术论文补全链：OpenAlex(DOI) → EuropePMC(标题) → Crossref(标题)
        await _enrich_paper(doc, client)


async def _enrich_epo_patent(doc: Dict, client: httpx.AsyncClient, token: Optional[str]):
    """EPO 专利：尝试从 description endpoint 获取前 500 字作为 pseudo-abstract"""
    if not token:
        return
    doc_id = doc.get("external_id", "")
    if not doc_id:
        return

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/xml"}

    # 尝试 description endpoint（全文描述，取前 500 字）
    try:
        url = f"{EPO_PUBLISHED}/{doc_id}/description"
        r = await client.get(url, headers=headers, timeout=10.0)
        if r.status_code == 200:
            text = _extract_description_text(r.text)
            if text and len(text) > 30:
                doc["abstract"] = text[:800]
                doc["_enriched_from"] = "epo_description"
                return
    except Exception as e:
        logger.debug("[Enricher] EPO description %s: %s", doc_id, e)


async def _enrich_paper(doc: Dict, client: httpx.AsyncClient):
    """学术论文：OpenAlex(DOI) → EuropePMC(标题) → Crossref(标题)"""
    # Step A: 有 DOI → OpenAlex
    doi = doc.get("doi")
    if doi:
        abstract = await _fetch_abstract_by_doi_openalex(doi, client)
        if abstract:
            doc["abstract"] = abstract
            doc["_enriched_from"] = "openalex"
            return

    title = doc.get("title", "").strip()
    if not title or len(title) <= 10:
        return

    # Step B: Europe PMC 标题搜索（比 Crossref 更容易返回 abstract）
    abstract = await _fetch_abstract_by_title_europepmc(title, client)
    if abstract:
        doc["abstract"] = abstract
        doc["_enriched_from"] = "europepmc"
        return

    # Step C: Crossref 标题搜索
    result = await _fetch_metadata_by_title_crossref(title, client)
    if result:
        if result.get("abstract") and not doc.get("abstract"):
            doc["abstract"] = result["abstract"]
            doc["_enriched_from"] = "crossref"
        if result.get("doi") and not doc.get("doi"):
            doc["doi"] = result["doi"]
        if result.get("citation_count") and (doc.get("citation_count") or 0) == 0:
            doc["citation_count"] = result["citation_count"]


def _extract_description_text(xml_text: str) -> Optional[str]:
    """从 EPO description XML 中提取纯文本（取前几段）"""
    if not xml_text:
        return None
    try:
        # 提取 <p> 标签内容
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', xml_text, re.DOTALL)
        if not paragraphs:
            # fallback: 去掉所有 XML 标签
            text = re.sub(r'<[^>]+>', ' ', xml_text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:800] if len(text) > 30 else None

        texts = []
        for p in paragraphs:
            clean = re.sub(r'<[^>]+>', ' ', p).strip()
            clean = re.sub(r'\s+', ' ', clean)
            if clean and len(clean) > 10:
                texts.append(clean)
            if sum(len(t) for t in texts) > 600:
                break

        return ' '.join(texts) if texts else None
    except Exception:
        return None


async def _fetch_abstract_by_doi_openalex(doi: str, client: httpx.AsyncClient) -> Optional[str]:
    """通过 DOI 从 OpenAlex 获取摘要"""
    try:
        doi_clean = doi.replace("https://doi.org/", "").strip()
        r = await client.get(
            f"{OPENALEX_WORKS}/doi:{doi_clean}",
            params={"mailto": "scholarpilot@example.com"},
        )
        if r.status_code == 200:
            data = r.json()
            inverted = data.get("abstract_inverted_index")
            if inverted:
                return _reconstruct_abstract(inverted)
    except Exception as e:
        logger.debug("[Enricher] OpenAlex DOI 查询失败: %s", e)
    return None


async def _fetch_abstract_by_title_europepmc(title: str, client: httpx.AsyncClient) -> Optional[str]:
    """通过标题从 Europe PMC 搜索获取摘要"""
    try:
        # Europe PMC 支持标题搜索且经常返回 abstract
        r = await client.get(
            EUROPEPMC_SEARCH,
            params={
                "query": f'TITLE:"{title[:150]}"',
                "resultType": "core",  # 包含 abstract
                "pageSize": 1,
                "format": "json",
            },
        )
        if r.status_code == 200:
            results = r.json().get("resultList", {}).get("result", [])
            if results:
                item = results[0]
                found_title = item.get("title", "")
                if _title_similar(title, found_title):
                    abstract = item.get("abstractText", "")
                    if abstract and len(abstract) > 50:
                        return re.sub(r'<[^>]+>', '', abstract).strip()
    except Exception as e:
        logger.debug("[Enricher] Europe PMC 标题搜索失败: %s", e)
    return None


async def _fetch_metadata_by_title_crossref(title: str, client: httpx.AsyncClient) -> Optional[Dict]:
    """通过标题从 Crossref 搜索获取元数据"""
    try:
        r = await client.get(
            CROSSREF_WORKS,
            params={
                "query.title": title[:200],
                "rows": 1,
                "select": "DOI,abstract,is-referenced-by-count,title",
                "mailto": "scholarpilot@example.com",
            },
        )
        if r.status_code == 200:
            items = r.json().get("message", {}).get("items", [])
            if items:
                item = items[0]
                found_titles = item.get("title", [])
                found_title = found_titles[0] if found_titles else ""
                if _title_similar(title, found_title):
                    abstract = item.get("abstract", "")
                    if abstract:
                        abstract = re.sub(r'<[^>]+>', '', abstract).strip()
                    return {
                        "doi": item.get("DOI"),
                        "abstract": abstract if abstract else None,
                        "citation_count": item.get("is-referenced-by-count", 0),
                    }
    except Exception as e:
        logger.debug("[Enricher] Crossref 标题搜索失败: %s", e)
    return None


def _title_similar(a: str, b: str) -> bool:
    """标题相似度检查（归一化后前 40 字符匹配）"""
    def normalize(t):
        return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', t.lower())[:40]
    return normalize(a) == normalize(b)


def _reconstruct_abstract(inverted_index: Dict) -> Optional[str]:
    """还原 OpenAlex 倒排索引格式的摘要"""
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


def compute_quality_score(doc: Dict) -> float:
    """计算文档元数据完整度分数 0.0-1.0"""
    score = 0.0
    if (doc.get("abstract") or "").strip():
        score += 0.30
    if doc.get("doi"):
        score += 0.20
    if (doc.get("citation_count") or 0) > 0:
        score += 0.20
    if doc.get("publication_date"):
        score += 0.15
    if doc.get("authors"):
        score += 0.15
    return round(score, 2)
