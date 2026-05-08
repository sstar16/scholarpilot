"""DocImportAgent — LLM 从 PDF 首 3 页文本提取文献元数据。

用于 M2 PDF 反向建文献流程：pdfplumber 抽文本 → 本 agent 转结构化元数据。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PdfMetadata:
    title: str = ""
    title_zh: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    doi: str | None = None
    journal: str | None = None
    one_line_summary: str = ""
    concept_tags: list[str] = field(default_factory=list)


_EXTRACT_PROMPT_TEMPLATE = """你是文献元数据抽取器。从以下 PDF 首 3 页文本抽取 JSON。

规则：
1. title 必填；若原文是英文保留英文（写到 title 字段），若能推断中文翻译写到 title_zh
2. authors 是字符串数组（["Vaswani", "Shazeer"]），最多 20 人
3. year 是 4 位数字（1900-2100 之间；找不到置 null）
4. abstract 不超过 1000 字符
5. doi 格式 "10.xxxx/xxxxx"，找不到置 null
6. one_line_summary 用中文总结这篇讲什么，200 字以内即可
7. concept_tags 3-8 个中文或英文关键词（研究主题/方法/领域）

PDF 文本：
---
{pdf_text}
---

只输出 JSON，不要任何前后缀解释。"""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _strip_json_fences(text: str) -> str:
    """LLM 有时包一层 ```json ... ```，剥掉。"""
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


class DocImportAgent:
    """Extract structured metadata from raw PDF text via LLM."""

    MAX_RETRIES = 3

    def __init__(self, llm_manager: Any):
        self._llm = llm_manager

    async def extract(self, pdf_text: str) -> PdfMetadata:
        """Return PdfMetadata; raises ValueError after MAX_RETRIES."""
        if not pdf_text or not pdf_text.strip():
            # Empty / blank PDF → let user fill everything manually
            return PdfMetadata()

        prompt = _EXTRACT_PROMPT_TEMPLATE.format(pdf_text=pdf_text[:12000])
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                raw = await self._llm.generate(
                    prompt, response_format={"type": "json_object"},
                )
                if not raw:
                    raise ValueError("LLM returned empty response")
                clean = _strip_json_fences(raw)
                data = json.loads(clean)
                return self._to_metadata(data)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = e
                logger.warning(
                    "[DocImportAgent] attempt %d/%d failed: %s",
                    attempt + 1, self.MAX_RETRIES, e,
                )

        raise ValueError(
            f"LLM failed to produce valid JSON after {self.MAX_RETRIES} retries: {last_error}"
        )

    @staticmethod
    def _to_metadata(data: dict) -> PdfMetadata:
        return PdfMetadata(
            title=str(data.get("title") or "").strip(),
            title_zh=data.get("title_zh") or None,
            authors=[str(a).strip() for a in (data.get("authors") or []) if str(a).strip()][:20],
            year=_safe_int(data.get("year")),
            abstract=str(data.get("abstract") or "")[:1000],
            doi=str(data.get("doi")).strip() if data.get("doi") else None,
            journal=str(data.get("journal")).strip() if data.get("journal") else None,
            one_line_summary=str(data.get("one_line_summary") or "")[:500],
            concept_tags=[str(t).strip() for t in (data.get("concept_tags") or []) if str(t).strip()][:8],
        )


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        n = int(v)
        if 1900 <= n <= 2100:
            return n
    except (TypeError, ValueError):
        pass
    return None
