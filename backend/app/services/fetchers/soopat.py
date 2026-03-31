"""
SooPat 中国专利搜索 Fetcher
https://www.soopat.com — 需要登录后的 session cookies

如何获取 cookies（Edge/Chrome）：
1. 打开浏览器，登录 soopat.com
2. 按 F12 → 网络（Network）→ 随便点一个请求 → 请求头（Headers）
3. 找到 Cookie 这一行，复制冒号后面的全部内容
4. 粘贴到 .env 的 SOOPAT_COOKIES=... 中

中国国内专利（CN发明/实用新型/外观设计）覆盖非常好
"""
import logging
import os
import re
from typing import Dict, List, Optional

import httpx

try:
    from bs4 import BeautifulSoup
    _BS4_OK = True
except ImportError:
    _BS4_OK = False

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

# SooPat 有时重定向到 www2，这里两个都试
SOOPAT_SEARCH_URL = "https://www.soopat.com/Home/Result"
SOOPAT_BASE = "https://www.soopat.com"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
)


class SooPatFetcher(AbstractFetcher):
    """SooPat 中国专利（CN）— BeautifulSoup HTML 解析，需登录 session cookies"""

    source_id = "soopat"
    DEFAULT_TIMEOUT = 20.0

    def __init__(self):
        self._cookies_str = os.getenv("SOOPAT_COOKIES", "")

    def _parse_cookies(self) -> dict:
        cookies: dict = {}
        for part in self._cookies_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    async def fetch(
        self, query: str, max_results=20, year_from=None, year_to=None, language=None
    ) -> List[Dict]:
        if not _BS4_OK:
            logger.error("[SooPat] beautifulsoup4 未安装，请重建镜像")
            return []
        if not self._cookies_str:
            logger.warning("[SooPat] SOOPAT_COOKIES 未配置，跳过")
            return []

        cookies = self._parse_cookies()
        headers = {
            "User-Agent": _UA,
            "Referer": SOOPAT_BASE + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        papers: List[Dict] = []
        page_size = 10
        pages_needed = min((max_results + page_size - 1) // page_size, 5)  # 最多50条

        async with httpx.AsyncClient(
            timeout=self.DEFAULT_TIMEOUT, follow_redirects=True
        ) as client:
            for page in range(pages_needed):
                if len(papers) >= max_results:
                    break
                params = {
                    "SearchWord": query,
                    "FMZL": "Y",  # 发明专利
                    "SYXX": "Y",  # 实用新型
                    "WGZL": "Y",  # 外观设计
                    "FMSQ": "Y",  # 发明申请
                    "PatentIndex": page * page_size,
                }
                # 年份范围（SooPat 支持 SQNF/SQNN 申请年份参数）
                if year_from:
                    params["SQNF"] = str(year_from)
                if year_to:
                    params["SQNN"] = str(year_to)

                try:
                    r = await client.get(
                        SOOPAT_SEARCH_URL,
                        params=params,
                        cookies=cookies,
                        headers=headers,
                    )
                    if r.status_code != 200:
                        logger.warning("[SooPat] HTTP %d (page %d)", r.status_code, page)
                        break

                    if "验证码" in r.text or "captcha" in r.text.lower():
                        logger.warning("[SooPat] 触发验证码，停止检索")
                        break

                    batch = self._parse_results(r.text)
                    logger.debug("[SooPat] 第%d页解析到 %d 条", page + 1, len(batch))
                    if not batch:
                        break
                    papers.extend(batch)

                except Exception as e:
                    logger.error("[SooPat] 第%d页请求失败: %s", page + 1, e)
                    break

        # 客户端年份后过滤（作为补充，弥补 SQNF/SQNN 可能不生效的情况）
        if year_from or year_to:
            filtered = []
            for p in papers:
                pub = p.get("publication_date") or ""
                try:
                    year = int(pub[:4]) if len(pub) >= 4 else None
                    if year_from and year and year < year_from:
                        continue
                    if year_to and year and year > year_to:
                        continue
                except Exception:
                    pass
                filtered.append(p)
            papers = filtered

        logger.info("[SooPat] 返回 %d 篇专利", len(papers[:max_results]))
        return papers[:max_results]

    def _parse_results(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        papers: List[Dict] = []

        # 专利结果块 — 尝试多种选择器（页面改版时降级）
        result_divs = (
            soup.find_all("div", style=lambda s: s and "min-height: 180px" in s)
            or soup.select("div.result-item")
            or soup.select("li.patent-item")
        )

        if not result_divs:
            logger.debug("[SooPat] 找不到结果块，HTML长度=%d", len(html))
            return []

        for div in result_divs:
            try:
                # ---- 标题 + 专利号 ----
                h2 = div.find("h2") or div.find("h3")
                if not h2:
                    continue
                a_tag = h2.find("a")
                if not a_tag:
                    continue

                full_text = a_tag.get_text(" ", strip=True)
                # 典型格式：[发明] 一种纳米粒子的制备方法 - CN201810123456A
                # 或：一种纳米粒子的制备方法 - CN201810123456A
                patent_type = ""
                font_tag = h2.find("font")
                if font_tag:
                    patent_type = font_tag.get_text(strip=True)  # e.g. [发明]
                    full_text = full_text.replace(patent_type, "").strip()

                if " - " in full_text:
                    parts = full_text.rsplit(" - ", 1)
                    title = parts[0].strip()
                    patent_num = parts[1].strip()
                else:
                    title = full_text.strip()
                    patent_num = ""

                href = a_tag.get("href", "")
                url = (SOOPAT_BASE + href) if href.startswith("/") else href or None

                # ---- 申请人 / 发明人 ----
                author_span = div.find("span", class_="PatentAuthorBlock")
                if author_span:
                    authors = ", ".join(
                        a.get_text(strip=True) for a in author_span.find_all("a")
                    )
                else:
                    # 备用：找所有带 申请人 / 发明人 标签
                    authors = _extract_label(div, ["申请人", "发明人"])

                # ---- 摘要 ----
                content_span = div.find("span", class_="PatentContentBlock")
                if content_span:
                    abstract = content_span.get_text(" ", strip=True)
                else:
                    abstract = _extract_label(div, ["摘要"]) or None

                # ---- 日期 ----
                pub_date = None
                for pattern in [r"(\d{4}-\d{2}-\d{2})", r"(\d{4}/\d{2}/\d{2})", r"(\d{4}\.\d{2}\.\d{2})"]:
                    m = re.search(pattern, div.get_text())
                    if m:
                        pub_date = m.group(1).replace("/", "-").replace(".", "-")
                        break

                papers.append({
                    "source": "soopat",
                    "external_id": patent_num or (href.split("/")[-1] if href else f"soop_{len(papers)}"),
                    "doc_type": "patent",
                    "title": title or patent_num,
                    "authors": authors,
                    "abstract": abstract,
                    "publication_date": pub_date,
                    "journal": f"SooPat {patent_type}".strip(),
                    "doi": None,
                    "citation_count": 0,
                    "pdf_url": None,
                    "url": url,
                })
            except Exception as e:
                logger.debug("[SooPat] 解析条目失败: %s", e)
                continue

        return papers


def _extract_label(div, labels: list) -> str:
    """在 div 文本中找 '标签：xxx' 模式，返回 xxx"""
    text = div.get_text(" ", strip=True)
    for label in labels:
        m = re.search(rf"{label}[：:]\s*(.+?)(?:\s{{2,}}|$)", text)
        if m:
            return m.group(1).strip()
    return ""
