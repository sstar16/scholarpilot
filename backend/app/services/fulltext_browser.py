"""
Fulltext Browser Fallback — 当纯 httpx 下载失败时，启动 Playwright 真浏览器
拿 PDF / HTML 快照。

设计参考：MediaCrawler 的 stealth 方案
  - libs/stealth.min.js（puppeteer-extra-stealth 提取版）消除 30+ 指纹特征
  - headless Chromium
  - 单个 context 只做一次 goto

只在 httpx 全链失败时才调用（启动 browser ~3-5 秒、image +400MB、
每次请求占用更多内存），所以这是最后的兜底。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STEALTH_JS_PATH = Path(__file__).parent / "stealth.min.js"


def _slugify(text: Optional[str], max_len: int = 60) -> str:
    if not text:
        return "untitled"
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", text)
    cleaned = re.sub(r'[<>:"/\\|?*\u00a0]', "_", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_. -")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_. -")
    return cleaned or "untitled"


def _project_dir_name(project_id: str, project_title: Optional[str] = None) -> str:
    if not project_title:
        return project_id
    slug = _slugify(project_title, max_len=40)
    short = project_id.split("-")[0][:8] if project_id else "noid"
    return f"{slug}_{short}"


_CITATION_PDF_RE = re.compile(
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


async def _setup_browser_context(browser):
    """创建带 stealth 注入的 Chromium context，模拟真实 Windows Chrome。"""
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/Los_Angeles",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        },
    )
    if _STEALTH_JS_PATH.exists():
        try:
            await context.add_init_script(path=str(_STEALTH_JS_PATH))
        except Exception as e:
            logger.warning("[BrowserFallback] 注入 stealth.min.js 失败: %r", e)
    return context


async def browser_download_pdf_or_html(
    landing_url: Optional[str],
    doi: Optional[str],
    project_id: str,
    pdf_base: Path,
    title: Optional[str] = None,
    project_title: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    用 Playwright 真浏览器访问 landing 页面，优先提取 citation_pdf_url → 下载 PDF，
    失败则保存 page.content() 作为 HTML 快照。

    Returns: (pdf_path, html_path, extracted_text_or_none)
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("[BrowserFallback] playwright 未安装，跳过 browser fallback")
        return None, None, None

    target = landing_url
    if not target and doi:
        clean_doi = doi
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if clean_doi.lower().startswith(prefix):
                clean_doi = clean_doi[len(prefix):]
        target = f"https://doi.org/{clean_doi}"
    if not target:
        return None, None, None

    proj_dir = pdf_base / _project_dir_name(project_id, project_title)
    proj_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(title)
    short_hash = hashlib.md5(target.encode()).hexdigest()[:8]
    pdf_path_local = proj_dir / f"{slug}_{short_hash}.pdf"
    html_path_local = proj_dir / f"{slug}_{short_hash}.html"

    pdf_result: Optional[str] = None
    html_result: Optional[str] = None
    text_result: Optional[str] = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = await _setup_browser_context(browser)
                page = await context.new_page()

                try:
                    # 等 network 空闲让动态内容加载完毕（给 lens.org 的 JS 反爬留时间）
                    await page.goto(target, wait_until="networkidle", timeout=30_000)
                except Exception as _goto_err:
                    logger.warning(
                        "[BrowserFallback] goto failed (continue anyway): %s err=%r",
                        target, _goto_err,
                    )

                # 策略 1：从页面里找 citation_pdf_url meta，尝试 request.get() 下载
                try:
                    html_content = await page.content()
                except Exception:
                    html_content = ""

                pdf_url_from_meta: Optional[str] = None
                if html_content:
                    m = _CITATION_PDF_RE.search(html_content)
                    if m:
                        pdf_url_from_meta = m.group(1)
                        if pdf_url_from_meta.startswith("/"):
                            from urllib.parse import urlparse
                            parsed = urlparse(target)
                            pdf_url_from_meta = (
                                f"{parsed.scheme}://{parsed.netloc}{pdf_url_from_meta}"
                            )

                async def _try_fetch_pdf(candidate_url: str, src_label: str) -> bool:
                    """用 browser context 下载候选 URL，检查是否为 PDF bytes。"""
                    nonlocal pdf_result
                    if pdf_result:
                        return True
                    try:
                        resp = await context.request.get(
                            candidate_url,
                            headers={"Referer": target},
                            timeout=30_000,
                        )
                        if not resp.ok:
                            return False
                        body = await resp.body()
                        if body[:5] == b"%PDF-" and len(body) > 1000:
                            pdf_path_local.write_bytes(body)
                            pdf_result = str(pdf_path_local)
                            logger.info(
                                "[BrowserFallback] PDF saved via %s: %s (%d bytes)",
                                src_label, pdf_path_local.name, len(body),
                            )
                            return True
                    except Exception as _err:
                        logger.warning(
                            "[BrowserFallback] %s fetch failed: %s err=%r",
                            src_label, candidate_url, _err,
                        )
                    return False

                # 策略 1a：citation_pdf_url meta
                if pdf_url_from_meta:
                    await _try_fetch_pdf(pdf_url_from_meta, "meta")

                # 策略 1b：页面扫 "Download PDF" / .pdf 链接（JMIR / 自建期刊 / preprint 等常见格式）
                if not pdf_result:
                    try:
                        # 1) 显式 text 按钮: <a>Download PDF</a> / <a>PDF</a> / <a>Full Text PDF</a>
                        candidates = await page.evaluate(
                            """() => {
                                const out = [];
                                const seen = new Set();
                                const add = (href) => {
                                    if (!href) return;
                                    const abs = new URL(href, location.href).toString();
                                    if (seen.has(abs)) return;
                                    seen.add(abs);
                                    out.push(abs);
                                };
                                // text 包含 PDF 的 anchor
                                document.querySelectorAll('a').forEach(a => {
                                    const txt = (a.innerText || a.textContent || '').trim().toLowerCase();
                                    const href = a.getAttribute('href') || '';
                                    if (!href) return;
                                    if (/download\\s*pdf|full[-\\s]?text\\s*pdf|view\\s*pdf|\\bpdf\\b/.test(txt)) {
                                        add(href);
                                    } else if (/\\.pdf($|\\?)/i.test(href)) {
                                        add(href);
                                    } else if (/download-pdf|\\/pdf\\//i.test(href)) {
                                        add(href);
                                    }
                                });
                                return out.slice(0, 10);
                            }"""
                        )
                        for cand in candidates or []:
                            if await _try_fetch_pdf(cand, "page-scan"):
                                break
                    except Exception as _scan_err:
                        logger.warning("[BrowserFallback] page-scan failed: %r", _scan_err)

                # 策略 2：保存 page HTML 作为快照（即使拿到 PDF 也顺便保存 HTML）
                if html_content and len(html_content) > 500:
                    html_path_local.write_text(html_content, encoding="utf-8")
                    html_result = str(html_path_local)
                    # 粗略提取正文
                    text = _strip_html_tags(html_content)[:50000]
                    if text:
                        text_result = text
                    logger.info(
                        "[BrowserFallback] HTML snapshot saved: %s (%d bytes)",
                        html_path_local.name, len(html_content),
                    )

                await context.close()
            finally:
                await browser.close()
    except Exception as e:
        logger.warning("[BrowserFallback] 整体失败 target=%s err=%r", target, e)
        return None, None, None

    return pdf_result, html_result, text_result


def _strip_html_tags(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
