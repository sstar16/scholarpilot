"""
EPO OPS (Open Patent Services) Fetcher
欧洲专利局官方免费 API — OAuth2 鉴权，覆盖 EP/WO/CN/US 等多局专利

申请免费账号：https://ops.epo.org → 注册 → 创建应用 → 获取 Consumer Key + Secret
免费配额：4 GB/周
"""
import logging
import os
from typing import Dict, List, Optional

import httpx

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

EPO_TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"


class EPOFetcher(AbstractFetcher):
    """EPO OPS 专利检索 — EP/WO 为主，也含 CN/US/JP 同族专利"""

    source_id = "epo_ops"
    DEFAULT_TIMEOUT = 25.0

    def __init__(self):
        self._consumer_key = os.getenv("EPO_CONSUMER_KEY", "")
        self._consumer_secret = os.getenv("EPO_CONSUMER_SECRET", "")

    async def _get_token(self, client: httpx.AsyncClient) -> Optional[str]:
        """OAuth2 client_credentials 换取 access_token（有效期 20 分钟）"""
        try:
            r = await client.post(
                EPO_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self._consumer_key, self._consumer_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
            if r.status_code == 200:
                return r.json().get("access_token")
            logger.warning("[EPO] token 获取失败: HTTP %d — %s", r.status_code, r.text[:120])
        except Exception as e:
            logger.error("[EPO] token 请求异常: %s", e)
        return None

    async def fetch(
        self, query: str, max_results=20, year_from=None, year_to=None, language=None
    ) -> List[Dict]:
        if not self._consumer_key or not self._consumer_secret:
            logger.warning("[EPO] EPO_CONSUMER_KEY / EPO_CONSUMER_SECRET 未配置，跳过")
            return []

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            token = await self._get_token(client)
            if not token:
                return []

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            # 构建 CQL 查询
            # EPO CQL 字段：ti=标题, ab=摘要, pa=申请人, ic=IPC分类
            words = [w.strip() for w in query.split() if len(w.strip()) > 2][:5]
            if not words:
                words = [query.strip()]

            if len(words) == 1:
                cql = f'ti="{words[0]}" OR ab="{words[0]}"'
            else:
                # 取前3个词，用 OR 连接，提高召回率
                parts = [f'(ti="{w}" OR ab="{w}")' for w in words[:3]]
                cql = " OR ".join(parts)

            # EPO CQL 日期范围语法：pd within "YYYYMMDD YYYYMMDD"
            if year_from and year_to:
                cql = f'({cql}) AND pd within "{year_from}0101 {year_to}1231"'
            elif year_from:
                import datetime
                cql = f'({cql}) AND pd within "{year_from}0101 {datetime.date.today().year}1231"'

            count = min(max_results, 50)
            params = {
                "q": cql,
                "Range": f"1-{count}",
            }

            try:
                r = await client.get(EPO_SEARCH_URL, params=params, headers=headers)
                if r.status_code == 200:
                    return self._parse_biblio(r.json(), count)
                elif r.status_code == 404:
                    logger.debug("[EPO] 查询无结果: %s", cql[:80])
                    return []
                else:
                    logger.warning("[EPO] 搜索失败: HTTP %d — %s", r.status_code, r.text[:200])
                    return []
            except Exception as e:
                logger.error("[EPO] fetch 异常: %s", e, exc_info=True)
                return []

    def _parse_biblio(self, data: dict, max_results: int) -> List[Dict]:
        papers: List[Dict] = []
        try:
            search_result = (
                data.get("ops:world-patent-data", {})
                    .get("ops:biblio-search", {})
                    .get("ops:search-result", {})
            )
            # exchange-documents 是一个列表，每个元素形如 {"exchange-document": {...}}
            exc_docs_raw = search_result.get("exchange-documents", [])
            if isinstance(exc_docs_raw, dict):
                exc_docs_raw = [exc_docs_raw]
            # 展开成 exchange-document 对象列表
            documents = []
            for wrapper in exc_docs_raw:
                doc = wrapper.get("exchange-document", {})
                if isinstance(doc, list):
                    documents.extend(doc)
                elif doc:
                    documents.append(doc)
        except Exception as e:
            logger.error("[EPO] 响应结构解析失败: %s", e)
            return []

        for doc in documents[:max_results]:
            try:
                biblio = doc.get("bibliographic-data", {})

                # 专利号
                pub_ref = biblio.get("publication-reference", {})
                doc_ids = pub_ref.get("document-id", [])
                if isinstance(doc_ids, dict):
                    doc_ids = [doc_ids]
                epodoc = next(
                    (d for d in doc_ids if d.get("@document-id-type") == "epodoc"),
                    doc_ids[0] if doc_ids else {},
                )
                country = _txt(epodoc.get("country"))
                doc_num = _txt(epodoc.get("doc-number"))
                kind = _txt(epodoc.get("kind"))
                patent_id = f"{country}{doc_num}{kind}".strip() or f"epo_{len(papers)}"

                # 公开日期
                pub_date_raw = _txt(epodoc.get("date"))
                publication_date = _fmt_date(pub_date_raw)

                # 标题（优先英文，无英文取第一个）
                titles = biblio.get("invention-title", [])
                if isinstance(titles, dict):
                    titles = [titles]
                title = ""
                for t in titles:
                    if t.get("@lang") == "en":
                        title = t.get("$", "")
                        break
                if not title and titles:
                    title = titles[0].get("$", "")

                # 摘要（优先英文）
                abstracts = biblio.get("abstract", [])
                if isinstance(abstracts, dict):
                    abstracts = [abstracts]
                abstract = None
                for ab in abstracts:
                    if ab.get("@lang") == "en":
                        # 摘要段落可能是 dict 或 list
                        p = ab.get("p", {})
                        abstract = _extract_text(p)
                        break
                if abstract is None and abstracts:
                    p = abstracts[0].get("p", {})
                    abstract = _extract_text(p)

                # 申请人 / 发明人
                parties = biblio.get("parties", {})
                applicant_text = _extract_party(parties.get("applicants", {}).get("applicant"))
                inventor_text = _extract_party(parties.get("inventors", {}).get("inventor"))
                authors = inventor_text or applicant_text

                papers.append({
                    "source": "epo_ops",
                    "external_id": patent_id,
                    "doc_type": "patent",
                    "title": title or patent_id,
                    "authors": authors,
                    "abstract": abstract,
                    "publication_date": publication_date,
                    "journal": f"EPO ({country})" if country else "EPO",
                    "doi": None,
                    "citation_count": 0,
                    "pdf_url": None,
                    "url": f"https://worldwide.espacenet.com/patent/search?q=pn%3D{patent_id}",
                })
            except Exception as e:
                logger.debug("[EPO] 解析单条文档失败: %s", e)
                continue

        logger.info("[EPO] 返回 %d 篇专利", len(papers))
        return papers


# ---------- 辅助函数 ----------

def _txt(field) -> str:
    """从 {"$": "value"} 或字符串中提取文本"""
    if not field:
        return ""
    if isinstance(field, dict):
        return field.get("$", "")
    return str(field)


def _fmt_date(raw: str) -> Optional[str]:
    """将 EPO 日期 '20230101' 转为 '2023-01-01'"""
    if not raw or len(raw) < 8:
        return raw or None
    try:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    except Exception:
        return raw


def _extract_text(p) -> Optional[str]:
    """从摘要 p 字段提取文本（可能是 dict、list 或字符串）"""
    if not p:
        return None
    if isinstance(p, str):
        return p
    if isinstance(p, dict):
        return p.get("$")
    if isinstance(p, list):
        parts = [_extract_text(item) for item in p if item]
        return " ".join(x for x in parts if x) or None
    return None


def _extract_party(raw) -> str:
    """从 applicant/inventor 字段提取名称列表（字段结构复杂）"""
    if not raw:
        return ""
    items = raw if isinstance(raw, list) else [raw]
    names = []
    for item in items[:5]:
        # item 可能是 {"applicant-name": {"name": {"$": "xxx"}}}
        for key in ("applicant-name", "inventor-name"):
            name_field = item.get(key, {})
            if isinstance(name_field, dict):
                n = _txt(name_field.get("name") or name_field.get("$"))
                if n:
                    names.append(n)
                    break
    if len(items) > 5:
        names.append("et al.")
    return ", ".join(names)
