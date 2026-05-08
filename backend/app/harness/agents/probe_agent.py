"""
Probe Agent — 对单篇论文做 section 级并行探针。

输入：question + full_text
→ split_into_sections 切段
→ asyncio.gather 并行跑每段探针
→ 返回命中 excerpts（按相关性降序）

为什么这样设计：
- 旧方案 full_text[:8000] 会丢失 Results/Discussion。探针按段扫描整文，不漏
- LLM 被强制"原文逐字引用"，杜绝探针阶段的幻觉
- 并行 asyncio.gather，单篇探针总延迟 ≈ 单次 LLM 调用
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import List, Optional

from app.harness.prompts.probe import build_probe_prompt
from app.harness.text_sectioning import Section, split_into_sections

logger = logging.getLogger(__name__)


MAX_SECTIONS_PER_DOC = 12       # 单篇最多跑这么多探针，防极长论文爆炸
MAX_EXCERPTS_PER_DOC = 6        # 单篇最多保留这么多命中，按相关性降序裁
RELEVANCE_THRESHOLD = 0.45      # 低于此视为无关，丢弃
EXCERPT_MAX_CHARS = 800         # 单 excerpt 长度上限（LLM 超了就截）


@dataclass
class ProbeExcerpt:
    doc_id: str
    section_idx: int
    section_label: str
    char_start: int
    char_end: int
    relevance: float
    excerpt_quote: str
    insight: str
    concepts: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


class ProbeAgent:
    """Section-level probe agent for deep reading."""

    def __init__(self, llm_manager=None):
        self._llm = llm_manager

    async def probe_document(
        self,
        question: str,
        doc_id: str,
        full_text: str,
        max_sections: int = MAX_SECTIONS_PER_DOC,
        max_excerpts: int = MAX_EXCERPTS_PER_DOC,
    ) -> List[ProbeExcerpt]:
        """
        跑完整一篇论文的探针。返回按 relevance 降序的命中 excerpts。
        """
        if not self._llm or not question.strip() or not full_text.strip():
            return []

        sections = split_into_sections(full_text)
        if not sections:
            return []
        sections = sections[:max_sections]

        logger.info(
            "[ProbeAgent] doc=%s sections=%d total_chars=%d",
            doc_id[:8], len(sections), len(full_text),
        )

        tasks = [
            self._probe_section(question, doc_id, sec)
            for sec in sections
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        hits: List[ProbeExcerpt] = []
        for sec, r in zip(sections, results):
            if isinstance(r, Exception):
                logger.warning(
                    "[ProbeAgent] section %d failed: %s", sec.idx, r,
                )
                continue
            if r is not None:
                hits.append(r)

        hits.sort(key=lambda e: e.relevance, reverse=True)
        trimmed = hits[:max_excerpts]
        logger.info(
            "[ProbeAgent] doc=%s hits=%d kept=%d (threshold=%.2f)",
            doc_id[:8], len(hits), len(trimmed), RELEVANCE_THRESHOLD,
        )
        return trimmed

    async def _probe_section(
        self,
        question: str,
        doc_id: str,
        section: Section,
    ) -> Optional[ProbeExcerpt]:
        system, user = build_probe_prompt(
            question=question,
            section_idx=section.idx,
            section_label=section.label,
            section_text=section.text,
            char_start=section.char_start,
            char_end=section.char_end,
        )
        combined = f"{system}\n\n---\n\n{user}"
        try:
            raw = await self._llm.generate(
                combined, temperature=0.1, max_tokens=1024,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.warning("[ProbeAgent] llm error sec=%d: %s", section.idx, e)
            return None
        if not raw:
            return None

        parsed = _parse_probe_response(raw)
        if not parsed:
            return None
        if not parsed.get("relevant"):
            return None
        rel = float(parsed.get("relevance_score") or 0)
        if rel < RELEVANCE_THRESHOLD:
            return None

        quote = (parsed.get("excerpt_quote") or "").strip()
        if not quote:
            return None
        quote = quote[:EXCERPT_MAX_CHARS]

        return ProbeExcerpt(
            doc_id=doc_id,
            section_idx=section.idx,
            section_label=section.label,
            char_start=section.char_start,
            char_end=section.char_end,
            relevance=max(0.0, min(1.0, rel)),
            excerpt_quote=quote,
            insight=(parsed.get("insight") or "").strip()[:300],
            concepts=[
                str(c).strip()[:60]
                for c in (parsed.get("concepts") or [])[:5]
                if str(c).strip()
            ],
        )


def _parse_probe_response(text: str) -> Optional[dict]:
    """宽松解析探针 JSON：先找首个 {...} 块，json.loads 失败返回 None。"""
    m = re.search(r"\{[\s\S]*?\}", text)
    if not m:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if "relevant" not in data:
        return None
    return data
