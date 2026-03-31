"""
SooPat 中国专利搜索 Fetcher
https://www.soopat.com

支持两种鉴权方式（优先级从高到低）：
  1. 账号密码自动登录（推荐）：配置 SOOPAT_EMAIL + SOOPAT_PASSWORD，无需手动操作
  2. 手动 Cookie：配置 SOOPAT_COOKIES（浏览器 F12 → 网络 → Cookie 请求头），会过期

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

SOOPAT_BASE = "https://www.soopat.com"
SOOPAT_LOGIN_URL = f"{SOOPAT_BASE}/Account/Login"
SOOPAT_SEARCH_URL = f"{SOOPAT_BASE}/Home/Result"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
)


class SooPatFetcher(AbstractFetcher):
    """SooPat 中国专利（CN） — 自动登录 + BeautifulSoup HTML 解析"""

    source_id = "soopat"
    DEFAULT_TIMEOUT = 45.0  # 登录需要3次HTTP请求，总耗时比其他数据源长

    def __init__(self):
        self._email = os.getenv("SOOPAT_EMAIL", "")
        self._password = os.getenv("SOOPAT_PASSWORD", "")
        self._manual_cookies_str = os.getenv("SOOPAT_COOKIES", "")
        # 内存中缓存登录后的 cookies（进程生命周期内复用）
        self._cached_cookies: Optional[httpx.Cookies] = None
        self._last_html: Optional[str] = None  # 调试用：保存最后一次 HTTP 响应 HTML

    # ------------------------------------------------------------------ #
    #  登录                                                                #
    # ------------------------------------------------------------------ #

    async def _login(self, client: httpx.AsyncClient) -> Optional[httpx.Cookies]:
        """
        自动登录，返回登录后的 httpx.Cookies。
        流程：GET 登录页（获取 hidden 字段）→ POST 表单 → 检查跳转
        """
        try:
            # Step 0：先访问首页，让服务端设置 _d_id 等必要 cookies
            await client.get(SOOPAT_BASE + "/", headers={"User-Agent": _UA}, timeout=10.0)

            # Step 1：获取登录页（含 ReturnUrl/Kickout hidden 字段）
            r = await client.get(SOOPAT_LOGIN_URL, headers={"User-Agent": _UA}, timeout=10.0)
            if r.status_code != 200:
                logger.warning("[SooPat] 登录页获取失败: HTTP %d", r.status_code)
                return None

            soup = BeautifulSoup(r.text, "lxml")
            form = soup.find("form")
            if not form:
                logger.warning("[SooPat] 登录页未找到表单")
                return None

            # 收集所有 hidden 字段
            payload: dict = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                val = inp.get("value", "")
                if name and inp.get("type") in ("hidden", None):
                    payload[name] = val

            # 填入凭证
            payload["Email"] = self._email
            payload["Password"] = self._password
            # 若账号在其他设备已登录，直接踢除（等同于点击弹窗中的"登录"按钮）
            payload["Kickout"] = "1"

            # Step 2：POST 登录
            r2 = await client.post(
                SOOPAT_LOGIN_URL,
                data=payload,
                headers={
                    "User-Agent": _UA,
                    "Referer": SOOPAT_LOGIN_URL,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                follow_redirects=True,
                timeout=15.0,
            )

            # 登录成功：重定向后应落在非登录页；若还在 /Account/Login 说明失败
            self._last_html = r2.text  # 保存登录响应以便诊断
            if "Account/Login" in str(r2.url):
                logger.warning("[SooPat] 登录失败（用户名或密码错误，或触发验证码）, response_len=%d", len(r2.text))
                return None

            # 提取 cookies（client 会自动维护 cookie jar）
            cookies = httpx.Cookies()
            for key, value in client.cookies.items():
                cookies.set(key, value, domain="www.soopat.com")

            logger.info("[SooPat] 自动登录成功，已获取 %d 个 cookies", len(list(client.cookies.items())))
            return cookies

        except Exception as e:
            logger.error("[SooPat] 登录异常: %s", e)
            return None

    def _manual_cookies(self) -> Optional[httpx.Cookies]:
        """从 SOOPAT_COOKIES 字符串解析 httpx.Cookies"""
        if not self._manual_cookies_str:
            return None
        cookies = httpx.Cookies()
        for part in self._manual_cookies_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies.set(k.strip(), v.strip(), domain="www.soopat.com")
        return cookies

    # ------------------------------------------------------------------ #
    #  Fetch                                                               #
    # ------------------------------------------------------------------ #

    async def fetch(
        self, query: str, max_results=20, year_from=None, year_to=None, language=None
    ) -> List[Dict]:
        if not _BS4_OK:
            logger.error("[SooPat] beautifulsoup4 未安装，请重建镜像")
            return []

        has_credentials = bool(self._email and self._password)
        has_manual = bool(self._manual_cookies_str)

        if not has_credentials and not has_manual:
            logger.warning("[SooPat] 未配置 SOOPAT_EMAIL/PASSWORD 或 SOOPAT_COOKIES，跳过")
            return []

        papers: List[Dict] = []
        page_size = 10
        pages_needed = min((max_results + page_size - 1) // page_size, 5)

        async with httpx.AsyncClient(
            timeout=self.DEFAULT_TIMEOUT,
            follow_redirects=True,
        ) as client:
            # 获取 cookies（优先账号密码自动登录）
            if has_credentials:
                if self._cached_cookies is None:
                    # 首次：直接用同一个 client 登录，cookies 自动落到 client 里
                    self._cached_cookies = await self._login(client)
                    if self._cached_cookies is None:
                        if has_manual:
                            logger.warning("[SooPat] 自动登录失败，降级使用手动 cookies")
                            _apply_cookies(client, self._manual_cookies())
                        else:
                            return []
                    # 登录成功：cookies 已在 client，无需再 update
                else:
                    # 后续 fetch() 调用：client 是新实例，需要注入缓存的 cookies
                    _apply_cookies(client, self._cached_cookies)
            else:
                manual = self._manual_cookies()
                if not manual:
                    return []
                _apply_cookies(client, manual)

            for page in range(pages_needed):
                if len(papers) >= max_results:
                    break

                params = {
                    "SearchWord": query,
                    "FMZL": "Y",
                    "SYXX": "Y",
                    "WGZL": "Y",
                    "FMSQ": "Y",
                    "PatentIndex": page * page_size,
                }
                if year_from:
                    params["SQNF"] = str(year_from)
                if year_to:
                    params["SQNN"] = str(year_to)

                try:
                    r = await client.get(
                        SOOPAT_SEARCH_URL,
                        params=params,
                        headers={
                            "User-Agent": _UA,
                            "Referer": SOOPAT_BASE + "/",
                            "Accept-Language": "zh-CN,zh;q=0.9",
                        },
                    )

                    self._last_html = r.text
                    logger.info("[SooPat] 第%d页 URL=%s status=%d html_len=%d",
                                page + 1, str(r.url)[:120], r.status_code, len(r.text))

                    # 检测 session 过期（follow_redirects=True 后落在登录页）
                    if "Account/Login" in str(r.url):
                        logger.info("[SooPat] session 已过期，尝试重新登录")
                        self._cached_cookies = None
                        if has_credentials:
                            # 重新登录：同一 client，cookies 自动注入
                            self._cached_cookies = await self._login(client)
                            if self._cached_cookies:
                                r = await client.get(SOOPAT_SEARCH_URL, params=params,
                                                     headers={"User-Agent": _UA})
                            else:
                                logger.warning("[SooPat] 重新登录失败，停止")
                                break
                        else:
                            logger.warning("[SooPat] 手动 cookies 已过期，请更新 SOOPAT_COOKIES")
                            break

                    if r.status_code != 200:
                        logger.warning("[SooPat] HTTP %d (page %d)", r.status_code, page)
                        break

                    if "验证码" in r.text or "captcha" in r.text.lower():
                        logger.warning("[SooPat] 触发验证码，停止检索")
                        break

                    patent_block_count = r.text.count('PatentBlock')
                    logger.info("[SooPat] 第%d页 PatentBlock数量=%d", page + 1, patent_block_count)

                    batch = self._parse_results(r.text)
                    logger.info("[SooPat] 第%d页解析到 %d 条", page + 1, len(batch))
                    if not batch:
                        break
                    papers.extend(batch)

                except Exception as e:
                    logger.error("[SooPat] 第%d页请求失败: %s", page + 1, e)
                    break

        # 客户端年份补充过滤
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

    # ------------------------------------------------------------------ #
    #  HTML 解析                                                           #
    # ------------------------------------------------------------------ #

    def _parse_results(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        papers: List[Dict] = []

        result_divs = (
            soup.find_all("div", class_="PatentBlock")
            or soup.find_all("div", style=lambda s: s and "min-height" in s and "max-width: 1080px" in s)
            or soup.select("div.result-item")
        )

        if not result_divs:
            logger.debug("[SooPat] 找不到结果块，HTML长度=%d", len(html))
            return []

        for div in result_divs:
            try:
                h2 = div.find("h2") or div.find("h3")
                if not h2:
                    continue
                a_tag = h2.find("a")
                if not a_tag:
                    continue

                full_text = a_tag.get_text(" ", strip=True)
                patent_type = ""
                font_tag = h2.find("font")
                if font_tag:
                    patent_type = font_tag.get_text(strip=True)
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

                author_span = div.find("span", class_="PatentAuthorBlock")
                if author_span:
                    authors = ", ".join(
                        a.get_text(strip=True) for a in author_span.find_all("a")
                    )
                else:
                    authors = _extract_label(div, ["申请人", "发明人"])

                content_span = div.find("span", class_="PatentContentBlock")
                abstract = content_span.get_text(" ", strip=True) if content_span else (
                    _extract_label(div, ["摘要"]) or None
                )

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


def _apply_cookies(client: httpx.AsyncClient, cookies: Optional[httpx.Cookies]) -> None:
    """将 httpx.Cookies 注入 client，逐个 set 避免 CookieConflict"""
    if not cookies:
        return
    for cookie in cookies.jar:
        client.cookies.set(cookie.name, cookie.value, domain=cookie.domain or "www.soopat.com")


def _extract_label(div, labels: list) -> str:
    text = div.get_text(" ", strip=True)
    for label in labels:
        m = re.search(rf"{label}[：:]\s*(.+?)(?:\s{{2,}}|$)", text)
        if m:
            return m.group(1).strip()
    return ""
