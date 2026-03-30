"""
元数据补全链
对缺少摘要的文档，尝试从 OpenAlex / Crossref 补全
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

OPENALEX_WORKS = "https://api.openalex.org/works"
CROSSREF_WORKS = "https://api.crossref.org/works"
MAX_ENRICH_PER_ROUND = 10
ENRICH_TIMEOUT = 10.0


async def enrich_missing_abstracts(docs: List[Dict]) -> List[Dict]:
    """
    对缺少 abstract 的文档，尝试从 OpenAlex / Crossref 补全。
    每轮最多补全 MAX_ENRICH_PER_ROUND 篇，避免 API 限速。
    """
    missing = [d for d in docs if not (d.get("abstract") or "").strip()]
    if not missing:
        return docs

    to_enrich = missing[:MAX_ENRICH_PER_ROUND]
    logger.info("[Enricher] %d 篇缺少摘要，尝试补全 %d 篇", len(missing), len(to_enrich))

    async with httpx.AsyncClient(timeout=ENRICH_TIMEOUT) as client:
        tasks = [_enrich_one(doc, client) for doc in to_enrich]
        await asyncio.gather(*tasks, return_exceptions=True)

    enriched_count = sum(1 for d in to_enrich if (d.get("abstract") or "").strip())
    logger.info("[Enricher] 成功补全 %d/%d 篇摘要", enriched_count, len(to_enrich))

    return docs


async def _enrich_one(doc: Dict, client: httpx.AsyncClient):
    """尝试从 OpenAlex → Crossref 链式补全单篇文档"""
    # Step A: 有 DOI → OpenAlex
    doi = doc.get("doi")
    if doi:
        abstract = await _fetch_abstract_by_doi_openalex(doi, client)
        if abstract:
            doc["abstract"] = abstract
            doc["_enriched_from"] = "openalex"
            return

    # Step B: 有 title → Crossref 搜索
    title = doc.get("title", "").strip()
    if title and len(title) > 10:
        result = await _fetch_metadata_by_title_crossref(title, client)
        if result:
            if result.get("abstract") and not doc.get("abstract"):
                doc["abstract"] = result["abstract"]
                doc["_enriched_from"] = "crossref"
            if result.get("doi") and not doc.get("doi"):
                doc["doi"] = result["doi"]
            if result.get("citation_count") and (doc.get("citation_count") or 0) == 0:
                doc["citation_count"] = result["citation_count"]


async def _fetch_abstract_by_doi_openalex(doi: str, client: httpx.AsyncClient) -> Optional[str]:
    """通过 DOI 从 OpenAlex 获取摘要"""
    try:
        # 标准化 DOI
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
                # 验证标题相似度（避免误匹配）
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
    """简单标题相似度检查（归一化后前 40 字符匹配）"""
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
