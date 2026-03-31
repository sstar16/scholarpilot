"""
中文学术数据源 Fetcher
当前实现：百度学术（非官方 HTML 解析）
目标：为 chinese_first scope 提供中文论文支持

注意：百度学术无官方 API，通过 HTML 解析实现，接口可能随时变化。
"""
import logging
import re
from typing import Dict, List, Optional
import httpx
from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

BAIDU_XUESHU_SEARCH = "https://xueshu.baidu.com/s"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://xueshu.baidu.com/",
}


def _parse_baidu_xueshu_html(html: str) -> List[Dict]:
    """从百度学术搜索结果 HTML 解析论文列表"""
    papers = []

    # 每条结果：<div class="result sc_default_result ...">
    result_blocks = re.split(r'<div[^>]+class="[^"]*result[^"]*sc_default_result[^"]*"', html)

    for block in result_blocks[1:]:  # 跳过第一个（页面头部）
        try:
            # 标题
            title_match = re.search(
                r'<a[^>]+class="[^"]*sc_hw[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL
            )
            if not title_match:
                # 备用：从 <h3> 中提取
                title_match = re.search(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            if not title_match:
                continue
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            if not title:
                continue

            # 摘要
            abstract_match = re.search(
                r'<div[^>]+class="[^"]*c_abstract[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL
            )
            abstract = None
            if abstract_match:
                abstract = re.sub(r'<[^>]+>', '', abstract_match.group(1)).strip()
                abstract = re.sub(r'\s+', ' ', abstract)

            # 作者：多个 <a class="author_text"> 或 c_author div
            author_matches = re.findall(
                r'<a[^>]+class="[^"]*author_text[^"]*"[^>]*>(.*?)</a>', block
            )
            if not author_matches:
                author_matches = re.findall(
                    r'<span[^>]+class="[^"]*author[^"]*"[^>]*>(.*?)</span>', block
                )
            authors = ", ".join(
                re.sub(r'<[^>]+>', '', a).strip()
                for a in author_matches[:5]
                if re.sub(r'<[^>]+>', '', a).strip()
            )

            # 年份：从 class="kw_main" 或发表信息行提取 4 位年份
            year_match = re.search(r'\b(19|20)\d{2}\b', block)
            year = year_match.group(0) if year_match else None
            pub_date = f"{year}-01-01" if year else None

            # 期刊/会议
            journal_match = re.search(
                r'<a[^>]+class="[^"]*kw_wr[^"]*"[^>]*>(.*?)</a>', block
            )
            journal = re.sub(r'<[^>]+>', '', journal_match.group(1)).strip() if journal_match else None

            # DOI 链接
            doi_match = re.search(r'doi\.org/(10\.[^\s"\'<>]+)', block)
            doi = doi_match.group(1) if doi_match else None

            # 论文跳转链接（百度学术详情页）
            url_match = re.search(r'<h3[^>]*>.*?<a\s+href="([^"]+)"', block, re.DOTALL)
            url = url_match.group(1) if url_match else None

            # 引用数
            cite_match = re.search(r'被引[：:]?\s*(\d+)', block)
            citation_count = int(cite_match.group(1)) if cite_match else 0

            papers.append({
                "source": "baidu_xueshu",
                "external_id": doi or title[:60],
                "doc_type": "paper",
                "title": title,
                "authors": authors or None,
                "abstract": abstract,
                "publication_date": pub_date,
                "journal": journal,
                "doi": doi,
                "citation_count": citation_count,
                "url": url,
                "pdf_url": None,
            })
        except Exception:
            continue

    return papers


class BaiduXueshuFetcher(AbstractFetcher):
    """百度学术数据源 — 中文论文主要来源"""
    source_id = "baidu_xueshu"
    DEFAULT_TIMEOUT = 25.0

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        papers = []
        page = 0
        per_page = 10

        # 百度学术支持中英文查询，中文查询效果更好
        async with httpx.AsyncClient(
            timeout=self.DEFAULT_TIMEOUT,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            try:
                # 先请求首页获取 session cookie，避免 403
                await client.get("https://xueshu.baidu.com/")

                while len(papers) < max_results and page < 3:
                    params = {
                        "wd": query,
                        "pn": page * per_page,
                        "tn": "SE_baiduxueshu_c1gjeupa",
                        "ie": "utf-8",
                        "sc_hit": "1",
                        "usm": "2",
                        "f": "8",
                    }
                    # 年份过滤
                    if year_from:
                        params["filter"] = f"time_range%3A{year_from}%2C{year_to or 9999}"

                    r = await client.get(BAIDU_XUESHU_SEARCH, params=params)
                    if r.status_code != 200:
                        logger.warning("[BaiduXueshu] HTTP %d（page=%d）", r.status_code, page)
                        break

                    batch = _parse_baidu_xueshu_html(r.text)
                    if not batch:
                        logger.debug("[BaiduXueshu] page=%d 无结果，停止翻页", page)
                        break

                    for p in batch:
                        if year_from and p.get("publication_date"):
                            try:
                                if int(p["publication_date"][:4]) < year_from:
                                    continue
                            except (ValueError, TypeError):
                                pass
                        papers.append(p)
                        if len(papers) >= max_results:
                            break

                    page += 1

            except Exception as e:
                logger.error("[BaiduXueshu] %s: %s", type(e).__name__, e, exc_info=True)

        logger.debug("[BaiduXueshu] 查询 '%s' 返回 %d 篇", query[:60], len(papers))
        return papers[:max_results]
