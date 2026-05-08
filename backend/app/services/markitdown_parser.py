"""
多格式文档解析统一入口（A1: markitdown 集成）

PDF 依然走 PyMuPDF（成熟稳定，已有多策略兜底）；
docx/pptx/xlsx/html/htm/md/txt/csv/json 等走 microsoft/markitdown。
图片/音频暂不接入（省 OCR/LLM 成本），需要时再加。

约定：
- 所有解析函数返回 str（Markdown 或纯文本）
- 失败抛 DocumentParseError，上层 Celery task 可捕获
- 单一入口：extract_document_text(path, filename) — 按扩展名分派
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DocumentParseError(Exception):
    """文档解析失败（上层 Celery task 会改 job.status=failed 并写 failure_reason）"""


# 扩展名 → 解析后端
PDF_EXTS = {".pdf"}
MARKITDOWN_EXTS = {
    ".docx", ".doc",
    ".pptx", ".ppt",
    ".xlsx", ".xls", ".csv",
    ".html", ".htm",
    ".md", ".markdown",
    ".txt",
    ".json", ".xml",
    ".epub",
    ".msg",
}
ALL_SUPPORTED_EXTS = PDF_EXTS | MARKITDOWN_EXTS


def get_file_kind(filename: str) -> str:
    """返回 'pdf' / 'markitdown' / 'unknown'。"""
    ext = Path(filename).suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in MARKITDOWN_EXTS:
        return "markitdown"
    return "unknown"


def is_supported(filename: str) -> bool:
    return get_file_kind(filename) != "unknown"


def extract_document_text(
    path: str,
    filename: Optional[str] = None,
    max_pdf_pages: int = 3,
    max_chars: int = 200_000,
) -> str:
    """按扩展名分派到对应解析器，返回 Markdown / 纯文本。

    max_pdf_pages: PDF 提取前 N 页（用于 metadata 抽取，不是全文）
    max_chars: 输出截断（避免超长文档把 prompt 撑爆）
    """
    fname = filename or os.path.basename(path)
    kind = get_file_kind(fname)

    if kind == "pdf":
        text = _extract_pdf_text(path, max_pages=max_pdf_pages)
    elif kind == "markitdown":
        text = _extract_markitdown(path)
    else:
        raise DocumentParseError(f"不支持的文件类型: {Path(fname).suffix}")

    text = (text or "").strip()
    if not text:
        raise DocumentParseError(f"解析后内容为空: {fname}")

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... 后续内容已截断 ...]"
    return text


# ── 后端实现 ──────────────────────────────────────────────

def _extract_pdf_text(path: str, max_pages: int = 3) -> str:
    """PyMuPDF 抽前 N 页文本。与 import_tasks._extract_pdf_text 行为一致。"""
    import fitz  # PyMuPDF

    parts: list[str] = []
    with fitz.open(path) as pdf:
        page_count = len(pdf)
        for i in range(min(max_pages, page_count)):
            page = pdf.load_page(i)
            text = page.get_text() or ""
            parts.append(text)
    return "\n\n".join(parts).strip()


def _extract_markitdown(path: str) -> str:
    """用 markitdown 把任意支持格式转成 Markdown。

    markitdown 是 lazy import，避免不装 markitdown 时整个 module 加载失败。
    """
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        raise DocumentParseError(
            "markitdown 未安装，请在 requirements.txt 启用并重 build"
        ) from e

    try:
        md = MarkItDown()
        result = md.convert(path)
        return result.text_content or ""
    except Exception as e:
        logger.exception("[markitdown] convert failed: %s", path)
        raise DocumentParseError(f"markitdown 解析失败: {e}") from e
