"""
Fulltext Service — PDF download + text extraction.

下载策略（多层兜底，每层用完整 Chrome stealth headers）：
1. 直接 GET pdf_url
2. unpaywall_lookup(doi) → OA PDF URL → GET
3. 解析 doi.org/{doi} 或 landing_url 的 HTML → 提取 <meta name="citation_pdf_url"> → GET
4. 全部失败 → HTML fallback 保存 landing page
"""
import hashlib
import logging
import os
import re
import random
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_PDF_BASE = Path("./data/pdfs")

# 完整 Chrome 136 真实 fingerprint（参考 MediaCrawler 反爬策略）
# 关键字段：sec-ch-ua-full-version-list（v120 以后的新字段，不带会被 MDPI/Cloudflare 等识别）
_CHROME_VERSION = "136.0.7103.114"
_BROWSER_HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-full-version-list": (
        f'"Chromium";v="{_CHROME_VERSION}", '
        f'"Google Chrome";v="{_CHROME_VERSION}", '
        '"Not.A/Brand";v="99.0.0.0"'
    ),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"19.0.0"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Priority": "u=0, i",
}


def _normalize_doi(raw: Optional[str]) -> Optional[str]:
    """剥掉 DOI 字符串的所有 URL 前缀，避免 'https://doi.org/https://doi.org/...' 双重前缀。"""
    if not raw:
        return None
    s = str(raw).strip()
    # 反复剥 prefix，兼容嵌套
    for _ in range(3):
        low = s.lower()
        stripped = False
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if low.startswith(prefix):
                s = s[len(prefix):].strip()
                stripped = True
                break
        if not stripped:
            break
    return s or None


def _pdf_headers() -> dict:
    """Headers tuned for fetching binary PDFs."""
    h = dict(_BROWSER_HEADERS_BASE)
    h["Accept"] = "application/pdf,application/octet-stream,*/*;q=0.8"
    h["Sec-Fetch-Dest"] = "embed"
    return h


def _html_headers(referer: Optional[str] = None) -> dict:
    """Headers tuned for fetching HTML landing pages."""
    h = dict(_BROWSER_HEADERS_BASE)
    h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    if referer:
        h["Referer"] = referer
    return h


def _is_pdf_response(resp) -> bool:
    """Detect if a response actually contains a PDF (not HTML error page)."""
    ct = (resp.headers.get("content-type") or "").lower()
    if "pdf" in ct:
        return True
    # Some servers return application/octet-stream — check magic bytes
    return resp.content[:5] == b"%PDF-"


def _slugify(text: Optional[str], max_len: int = 60) -> str:
    """
    Convert a title to a filesystem-safe slug, preserving CJK characters.
    Examples:
      "Abuse liability of two electronic..." -> "Abuse_liability_of_two_electronic"
      "一种固态锂电池电解质组合物" -> "一种固态锂电池电解质组合物"
      None / "" -> "untitled"
    """
    if not text:
        return "untitled"
    # Strip control chars
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", text)
    # Replace filesystem-unsafe chars with underscore
    cleaned = re.sub(r'[<>:"/\\|?*\u00a0]', "_", cleaned)
    # Replace various whitespace runs with single underscore
    cleaned = re.sub(r"\s+", "_", cleaned)
    # Collapse multiple underscores
    cleaned = re.sub(r"_+", "_", cleaned)
    # Strip leading/trailing punctuation that's awkward in filenames
    cleaned = cleaned.strip("_. -")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_. -")
    return cleaned or "untitled"


def _project_dir_name(project_id: str, project_title: Optional[str] = None) -> str:
    """Build a readable project directory name: '<slug>_<8-char-uuid>'.
    Falls back to bare project_id when title is missing.
    """
    if not project_title:
        return project_id
    slug = _slugify(project_title, max_len=40)
    short = project_id.split("-")[0][:8] if project_id else "noid"
    return f"{slug}_{short}"


async def _save_pdf_bytes(
    content: bytes,
    project_id: str,
    source_url: str,
    pdf_base: Path,
    title: Optional[str] = None,
    project_title: Optional[str] = None,
) -> str:
    """Persist PDF bytes to disk and return local path.
    Filename = "<slug-of-title>_<8-char-hash>.pdf" — readable + unique.
    Directory = "<project-slug>_<short-uuid>" — also human readable.
    """
    proj_dir = pdf_base / _project_dir_name(project_id, project_title)
    proj_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(title)
    short_hash = hashlib.md5(source_url.encode()).hexdigest()[:8]
    local_path = proj_dir / f"{slug}_{short_hash}.pdf"

    local_path.write_bytes(content)
    logger.info(
        "[Fulltext] PDF saved: %s (%d bytes) from %s",
        local_path.name, len(content), source_url,
    )
    return str(local_path)


async def _try_fetch_pdf(client, url: str, referer: Optional[str] = None) -> Optional[bytes]:
    """Single PDF GET attempt with stealth headers. Returns bytes or None."""
    try:
        resp = await client.get(url, headers=_pdf_headers() if not referer else {**_pdf_headers(), "Referer": referer})
        if resp.status_code == 200 and len(resp.content) > 1000 and _is_pdf_response(resp):
            return resp.content
        logger.warning(
            "[Fulltext] PDF rejected: status=%d size=%d ct=%s url=%s",
            resp.status_code, len(resp.content),
            resp.headers.get("content-type", "?")[:40], url,
        )
    except Exception as e:
        logger.warning("[Fulltext] PDF GET failed for %s: %r", url, e)
    return None


_CITATION_PDF_RE = re.compile(
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


async def _extract_citation_pdf_from_html(client, landing_url: str) -> Optional[str]:
    """Fetch the landing page HTML and extract <meta name="citation_pdf_url">.
    This is the universally-supported way that academic publishers expose
    PDF URLs (Highwire-style metadata).
    """
    try:
        resp = await client.get(landing_url, headers=_html_headers())
        if resp.status_code != 200:
            logger.warning(
                "[Fulltext] Landing page rejected: status=%d url=%s",
                resp.status_code, landing_url,
            )
            return None
        m = _CITATION_PDF_RE.search(resp.text)
        if m:
            pdf_url = m.group(1)
            # Resolve relative URLs
            if pdf_url.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(str(resp.url))
                pdf_url = f"{parsed.scheme}://{parsed.netloc}{pdf_url}"
            logger.info("[Fulltext] Found citation_pdf_url: %s (from %s)", pdf_url, landing_url)
            return pdf_url
        logger.info("[Fulltext] No citation_pdf_url meta in %s", landing_url)
    except Exception as e:
        logger.warning("[Fulltext] Landing page fetch failed for %s: %r", landing_url, e)
    return None


async def download_pdf(
    pdf_url: Optional[str],
    doi: Optional[str],
    project_id: str = "default",
    pdf_base: Path = DEFAULT_PDF_BASE,
    landing_url: Optional[str] = None,
    title: Optional[str] = None,
    project_title: Optional[str] = None,
    source: Optional[str] = None,
    external_id: Optional[str] = None,
) -> Optional[str]:
    """
    Multi-strategy PDF downloader.

    **付费 PDF 源专用分支**（最高优先级）：fetcher.PAID_PDF=True
      → 调 fetcher.download_pdf_for_doc(doc_meta, outfile)，由 fetcher 用自己
      的鉴权 + 详情接口 + key 解析等下载 PDF。预算守门由 API 路由完成（worker 不管）。

    其他源（PAID_PDF=False）多策略兜底（按顺序）：
      1. Direct GET pdf_url
      2. unpaywall_lookup(doi) → OA URL → GET
      3. doi.org/{doi} → landing page → citation_pdf_url meta → GET
      4. landing_url → landing page → citation_pdf_url meta → GET
    Returns local file path or None.
    """
    import httpx
    from app.services.fetchers.international import ALL_FETCHERS

    fetcher = ALL_FETCHERS.get(source) if source else None
    if fetcher is not None and getattr(fetcher, "PAID_PDF", False):
        if not external_id:
            logger.warning(
                "[Fulltext] %s 是付费 PDF 源但 doc 缺 external_id，跳过", source,
            )
            return None

        proj_dir = pdf_base / _project_dir_name(project_id, project_title)
        slug = _slugify(title)
        short_hash = hashlib.md5(external_id.encode()).hexdigest()[:8]
        outfile = proj_dir / f"{slug}_{short_hash}.pdf"

        doc_meta: Dict[str, Optional[str]] = {
            "external_id": external_id,
            "patent_number": external_id,  # patenthub 历史别名（fetcher 自己挑用哪个）
            "pdf_url": pdf_url,
            "doi": doi,
            "title": title,
        }
        ok = await fetcher.download_pdf_for_doc(doc_meta, outfile)
        if ok:
            logger.info("[Fulltext] %s PDF 已保存 %s (%d bytes)",
                        source, outfile.name, outfile.stat().st_size)
            return str(outfile)
        logger.warning("[Fulltext] %s PDF 下载失败 ext_id=%s", source, external_id)
        return None

    doi = _normalize_doi(doi)

    candidate_urls: list[tuple[str, Optional[str]]] = []  # (url, referer)
    if pdf_url:
        candidate_urls.append((pdf_url, None))

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=_BROWSER_HEADERS_BASE,
    ) as client:
        # Strategy 1: try direct pdf_url(s) first
        for url, referer in candidate_urls:
            content = await _try_fetch_pdf(client, url, referer)
            if content:
                return await _save_pdf_bytes(content, project_id, url, pdf_base, title=title, project_title=project_title)

        # Strategy 2: unpaywall lookup
        if doi:
            oa_url = await unpaywall_lookup(doi)
            if oa_url:
                content = await _try_fetch_pdf(client, oa_url)
                if content:
                    return await _save_pdf_bytes(content, project_id, oa_url, pdf_base, title=title, project_title=project_title)

        # Strategy 3: doi.org → landing page → citation_pdf_url
        # doi 此时已 normalize 过，不会出现 doi.org/https://doi.org/ 的双重前缀
        if doi:
            doi_landing = f"https://doi.org/{doi}"
            cite_pdf = await _extract_citation_pdf_from_html(client, doi_landing)
            if cite_pdf:
                content = await _try_fetch_pdf(client, cite_pdf, referer=doi_landing)
                if content:
                    return await _save_pdf_bytes(content, project_id, cite_pdf, pdf_base, title=title, project_title=project_title)

        # Strategy 4: explicit landing_url
        if landing_url and landing_url not in (pdf_url,):
            cite_pdf = await _extract_citation_pdf_from_html(client, landing_url)
            if cite_pdf:
                content = await _try_fetch_pdf(client, cite_pdf, referer=landing_url)
                if content:
                    return await _save_pdf_bytes(content, project_id, cite_pdf, pdf_base, title=title, project_title=project_title)

    logger.warning(
        "[Fulltext] All PDF strategies failed (pdf_url=%s, doi=%s, landing=%s)",
        pdf_url, doi, landing_url,
    )
    return None


async def unpaywall_lookup(doi: str) -> Optional[str]:
    """Look up OA PDF via Unpaywall API."""
    # 关键：剥掉 https://doi.org/ 前缀，避免拼出 api.unpaywall.org/v2/https://doi.org/...
    doi = _normalize_doi(doi)
    if not doi:
        return None
    try:
        import httpx
        from urllib.parse import quote
        from app.config import settings
        # Defensive: treat empty string as missing
        email = (getattr(settings, "unpaywall_email", None) or "").strip()
        if not email:
            email = "scholarpilot@anthropic.com"
        # DOI 里可能含 '/'，按 URL path component 编码
        encoded = quote(doi, safe="")
        url = f"https://api.unpaywall.org/v2/{encoded}?email={email}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_BROWSER_HEADERS_BASE)
            if resp.status_code == 200:
                data = resp.json()
                best = data.get("best_oa_location") or {}
                pdf = best.get("url_for_pdf") or best.get("url")
                if pdf:
                    logger.info("[Fulltext] Unpaywall OA found for %s: %s", doi, pdf)
                    return pdf
            else:
                logger.warning(
                    "[Fulltext] Unpaywall returned %d for doi=%s",
                    resp.status_code, doi,
                )
    except Exception as e:
        logger.warning("[Fulltext] Unpaywall lookup failed for %s: %r", doi, e)
    return None


async def extract_text(pdf_path: str, max_chars: int = 150_000) -> Optional[str]:
    """Extract text from a PDF file. Tries PyMuPDF first, then pdfplumber.

    上限 150K（2026-05-03）：旧 50K 是给 GPT-4 32K 上下文写的保守值；现在 LLM
    都吃 100K-1M tokens，且 ProbeAgent 按 IMRaD section 切段并行探针 + 缓存，
    要的是完整全文不是采样。150K 字符 ≈ 40K tokens，覆盖 95%+ 学术 PDF 全量。

    旧 ``extract_text_smart`` 的分级抽样（head_tail_sample / sparse_sample）已废弃 —
    那套是为了"装进 LLM 上下文 + DB 列"两个夹逼场景写的，现在两边都不需要。
    长文档相关性判断交给下游 ProbeAgent 做 section 级精读，不在此层裁剪。
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
            if len("\n".join(text_parts)) > max_chars:
                break
        doc.close()
        text = "\n".join(text_parts).strip()
        return text if len(text) > 100 else None
    except ImportError:
        pass

    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            # 没装 fitz 才走这条；pdfplumber 慢，pages[:60] 折中
            for page in pdf.pages[:60]:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
                if len("\n".join(text_parts)) > max_chars:
                    break
        text = "\n".join(text_parts).strip()
        return text if len(text) > 100 else None
    except ImportError:
        logger.warning("[Fulltext] No PDF parser available (install PyMuPDF or pdfplumber)")

    return None


async def download_html_fallback(
    landing_url: Optional[str],
    doi: Optional[str],
    project_id: str = "default",
    pdf_base: Path = DEFAULT_PDF_BASE,
    title: Optional[str] = None,
    project_title: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Fallback when PDF download fails: try to fetch the HTML landing page.
    Saves HTML to disk and returns (local_path, extracted_text).

    反爬策略:
      - status=202 ("Accepted, 处理中") 视为临时可重试：指数退避重试 2 次
      - lens.org 的 202 通常需要等待几秒才会返回真正的 HTML
      - 接受 "html" 或 "text" 类型的响应，并要求 content 非空
    """
    # 归一化 doi，避免 https://doi.org/https://doi.org/... 双重前缀
    doi = _normalize_doi(doi)
    target = landing_url
    if not target and doi:
        target = f"https://doi.org/{doi}"
    if not target:
        return None, None

    try:
        import httpx
        import asyncio
        proj_dir = pdf_base / _project_dir_name(project_id, project_title)
        proj_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(title)
        short_hash = hashlib.md5(target.encode()).hexdigest()[:8]
        local_path = proj_dir / f"{slug}_{short_hash}.html"

        if local_path.exists() and local_path.stat().st_size > 500:
            return str(local_path), None

        # 最多 3 次尝试（含首次）— lens 等站常见第一次 202，第二/三次才真正返回
        delays = [0.0, 2.5, 5.0]
        async with httpx.AsyncClient(
            timeout=25.0,
            follow_redirects=True,
            headers=_html_headers(),
        ) as client:
            for attempt_idx, delay in enumerate(delays):
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    resp = await client.get(target)
                except Exception as _fetch_err:
                    logger.warning(
                        "[Fulltext] HTML fallback attempt %d fetch error for %s: %r",
                        attempt_idx + 1, target, _fetch_err,
                    )
                    continue

                ct = (resp.headers.get("content-type") or "").lower()
                is_html_ct = "html" in ct or "text" in ct or ct == ""
                content_ok = len(resp.content) > 500

                # 200 + 有内容 + html → 直接保存
                if resp.status_code == 200 and content_ok and is_html_ct:
                    local_path.write_bytes(resp.content)
                    logger.info(
                        "[Fulltext] HTML fallback saved: %s (%d bytes, attempt=%d)",
                        local_path.name, len(resp.content), attempt_idx + 1,
                    )
                    return str(local_path), _strip_html_tags(resp.text)[:50000]

                # 202 + 有内容：lens.org 会返回一个"处理中"页面，但有时也能用
                # 先尝试重试；如果是最后一次尝试就接受这个内容当作 HTML 快照
                if resp.status_code == 202:
                    if attempt_idx < len(delays) - 1:
                        logger.info(
                            "[Fulltext] HTML fallback got 202 (processing), retry %d/%d after %ss: %s",
                            attempt_idx + 1, len(delays), delays[attempt_idx + 1], target,
                        )
                        continue
                    if content_ok and is_html_ct:
                        local_path.write_bytes(resp.content)
                        logger.info(
                            "[Fulltext] HTML fallback accepted 202 body as snapshot: %s (%d bytes)",
                            local_path.name, len(resp.content),
                        )
                        return str(local_path), _strip_html_tags(resp.text)[:50000]

                # 403/429/5xx 等其它状态 — 重试
                if resp.status_code in (403, 429, 500, 502, 503, 504) \
                        and attempt_idx < len(delays) - 1:
                    logger.info(
                        "[Fulltext] HTML fallback status=%d, retry %d/%d: %s",
                        resp.status_code, attempt_idx + 1, len(delays), target,
                    )
                    continue

                logger.warning(
                    "[Fulltext] HTML fallback rejected: status=%d size=%d ct=%s url=%s",
                    resp.status_code, len(resp.content), ct[:40], target,
                )
                break
    except Exception as e:
        logger.warning("[Fulltext] HTML fallback failed for %s: %r", target, e)

    return None, None


def _strip_html_tags(html: str) -> str:
    """Crude HTML → text. Good enough for fallback indexing."""
    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def download_and_extract(
    pdf_url: Optional[str],
    doi: Optional[str],
    project_id: str = "default",
    landing_url: Optional[str] = None,
    title: Optional[str] = None,
    project_title: Optional[str] = None,
    format: str = "auto",
    source: Optional[str] = None,
    external_id: Optional[str] = None,
) -> dict:
    """
    Download fulltext in requested format(s).

    format:
      - "auto": 先尝试 PDF，失败则退到 HTML landing。
      - "pdf":  只尝试 PDF，不做 HTML fallback。
      - "html": 只抓 landing HTML 快照（不尝试 PDF 提取），适合用户明确想要
                网页形式、或者 PDF 已经存在又想补一份 HTML 的场景。

    Returns dict:
      {
        "pdf_path": Optional[str],   # 本地 PDF 路径
        "pdf_text": Optional[str],   # PDF 提取的纯文本
        "html_path": Optional[str],  # 本地 HTML 路径
        "html_text": Optional[str],  # HTML 提取的纯文本
      }
    任一通道失败对应字段为 None；调用方根据是否有 path 判断成功。
    """
    result: dict = {
        "pdf_path": None,
        "pdf_text": None,
        "html_path": None,
        "html_text": None,
    }

    want_pdf = format in ("auto", "pdf")
    want_html = format in ("auto", "html")

    if want_pdf:
        pdf_path = await download_pdf(
            pdf_url, doi, project_id,
            landing_url=landing_url, title=title, project_title=project_title,
            source=source, external_id=external_id,
        )
        if pdf_path:
            result["pdf_path"] = pdf_path
            result["pdf_text"] = await extract_text(pdf_path)

    # auto 模式：PDF 成不成功都额外下一份 HTML（两种形式可共存）
    if want_html:
        html_path, html_text = await download_html_fallback(
            landing_url=landing_url, doi=doi, project_id=project_id,
            title=title, project_title=project_title,
        )
        if html_path:
            result["html_path"] = html_path
            result["html_text"] = html_text

    # ─── Phase 2 兜底：httpx 链路全部失败时启动 Playwright 真浏览器 ───
    # 条件：当前请求的格式在"httpx 通道"完全没拿到，且有 landing_url/doi 可试
    #   auto 模式: 两个通道都 None → 上 browser（最大成功率）
    #   pdf 模式:  pdf_path 是 None → 上 browser（只看 PDF）
    #   html 模式: html_path 是 None → 上 browser（只看 HTML）
    need_browser = False
    if format == "auto" and not result["pdf_path"] and not result["html_path"]:
        need_browser = True
    elif format == "pdf" and not result["pdf_path"]:
        need_browser = True
    elif format == "html" and not result["html_path"]:
        need_browser = True

    # 资源紧张的 backend（如 client-only 4G 香港机）整体禁用 browser fallback：
    # 多 worker × playwright chromium 容易把 RAM 拉爆。设 DISABLE_FULLTEXT_BROWSER=1 跳过。
    if need_browser and os.getenv("DISABLE_FULLTEXT_BROWSER", "").lower() in ("1", "true", "yes"):
        logger.info("[Fulltext] DISABLE_FULLTEXT_BROWSER=1 → skip browser fallback")
        need_browser = False

    if need_browser and (landing_url or doi):
        try:
            from app.services.fulltext_browser import browser_download_pdf_or_html
            logger.info(
                "[Fulltext] httpx 全链失败，启动 Playwright browser fallback: landing=%s",
                landing_url or f"doi:{doi}",
            )
            br_pdf, br_html, br_text = await browser_download_pdf_or_html(
                landing_url=landing_url,
                doi=doi,
                project_id=project_id,
                pdf_base=DEFAULT_PDF_BASE,
                title=title,
                project_title=project_title,
            )
            if br_pdf and not result["pdf_path"]:
                result["pdf_path"] = br_pdf
                # 用 PyMuPDF 重新抽文本
                result["pdf_text"] = await extract_text(br_pdf)
            if br_html and not result["html_path"]:
                result["html_path"] = br_html
                result["html_text"] = br_text
        except Exception as _br_err:
            logger.warning("[Fulltext] Browser fallback 失败（非致命）: %r", _br_err)

    return result
