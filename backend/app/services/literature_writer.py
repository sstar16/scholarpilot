"""
LiteratureWriter — 把每篇论文持久化为 per-project .md workspace.

S1 作为 _generate_summary_async + _finalize_round_async + backfill 的内部客户调用 file_tools.
S2 会让 LLM agent 也通过 ToolRegistry 使用同一套 fs_* 工具。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import yaml

from app.harness.file_tools.context import ToolContext
from app.harness.file_tools.registry import ToolRegistry
from app.harness.file_tools.sandbox import PathSandbox
from app.harness.file_tools.tools.fs_glob import FsGlobInput
from app.harness.file_tools.tools.fs_read import FsReadInput
from app.harness.file_tools.tools.fs_write import FsWriteInput
from app.services.text_slug import slugify

logger = logging.getLogger(__name__)


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def make_slug(doc_id: str, title: Optional[str]) -> str:
    """Generate a stable slug for a document.

    Format: {clean_title[:50]}_{doc_uuid_short}
    E.g. "attention-is-all-you-need_a1b2c3d4"
    """
    clean = slugify(title or "untitled", max_len=50) or "untitled"
    short = str(doc_id).replace("-", "")[:8]
    return f"{clean}_{short}"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body. Returns (frontmatter_dict, body_str).

    If no frontmatter is present, returns ({}, text).
    Malformed YAML raises yaml.YAMLError — callers should catch and log.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    yaml_block = m.group(1)
    body = m.group(2)
    fm = yaml.safe_load(yaml_block) or {}
    if not isinstance(fm, dict):
        return {}, text
    return fm, body


def replace_frontmatter_field(text: str, key: str, value: Any) -> str:
    """In-place rewrite: update a single frontmatter field and re-emit the file.

    Used by update_bucket to change `bucket:` without re-running LLM.
    """
    fm, body = parse_frontmatter(text)
    fm[key] = value
    new_yaml = yaml.safe_dump(
        fm, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip()
    return f"---\n{new_yaml}\n---\n{body}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class LiteratureWriter:
    """Writes per-document .md files into a project's sandboxed workspace."""

    def __init__(self, project_id: str, registry: ToolRegistry) -> None:
        self.project_id = project_id
        self.sandbox = PathSandbox(project_id)
        self.ctx = ToolContext(project_id=project_id, sandbox=self.sandbox)
        self.fs_read = registry.find("fs_read")
        self.fs_glob = registry.find("fs_glob")
        self.fs_write = registry.find("fs_write")
        if not (self.fs_read and self.fs_glob and self.fs_write):
            raise RuntimeError("file_tools registry missing fs_read/glob/write")

    async def persist(
        self,
        doc: dict,
        bucket: Optional[str],
        llm_result: dict,
    ) -> str:
        """Write single .md. Returns slug (without .md extension)."""
        slug = make_slug(doc["id"], doc.get("title"))
        md = self._render_markdown(doc, bucket, llm_result, slug)
        await self.fs_write.call(
            FsWriteInput(path=f"literature/{slug}.md", content=md),
            self.ctx,
        )
        logger.info(
            "[LibWriter] project=%s doc=%s slug=%s bytes=%d status=ok",
            self.project_id[:8], str(doc["id"])[:8], slug, len(md),
        )
        return slug

    # ------------------------------------------------------------------
    # Markdown template
    # ------------------------------------------------------------------

    def _render_markdown(
        self,
        doc: dict,
        bucket: Optional[str],
        llm: dict,
        slug: str,
    ) -> str:
        """Compose frontmatter + body."""
        fm = self._build_frontmatter(doc, bucket, llm, slug)
        body = self._build_body(doc, llm)

        fm_yaml = yaml.safe_dump(
            fm, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).rstrip()
        return f"---\n{fm_yaml}\n---\n\n{body}"

    def _build_frontmatter(
        self,
        doc: dict,
        bucket: Optional[str],
        llm: dict,
        slug: str,
    ) -> dict:
        # Truncate + sanitize LLM extraction fields
        concepts = llm.get("concepts") or []
        methods = llm.get("methods") or []
        results = llm.get("results") or []
        citations = llm.get("citations_mentioned") or []

        return {
            "id": str(doc["id"]),
            "slug": slug,
            "source": doc.get("source"),
            "external_id": doc.get("external_id"),
            "doi": doc.get("doi"),
            "title": doc.get("title"),
            "title_zh": doc.get("title_zh"),
            "authors": self._split_authors(doc.get("authors")),
            "year": self._extract_year(doc.get("publication_date")),
            "journal": doc.get("journal"),
            "publication_date": str(doc.get("publication_date") or ""),
            "url": doc.get("url"),
            "pdf_url": doc.get("pdf_url"),
            "bucket": bucket,
            "quality_score": doc.get("quality_score") or llm.get("quality_score"),
            "round_id": doc.get("round_id"),
            "concepts": concepts,
            "methods": methods,
            "results": results,
            "citations_mentioned": citations,
            "ai_summary_source": doc.get("ai_summary_source") or "from_abstract",
            "fulltext_available": bool(doc.get("fulltext_text")),
            "extract_status": llm.get("_extract_status", "ok"),
            "updated_at": _now_iso(),
            "kg_synced": False,
        }

    def _build_body(self, doc: dict, llm: dict) -> str:
        title = doc.get("title") or "Untitled"
        one_line = llm.get("one_line_summary") or doc.get("one_line_summary") or ""
        summary = llm.get("summary") or doc.get("ai_summary") or ""
        key_points = llm.get("key_points") or doc.get("ai_key_points") or []
        abstract = doc.get("abstract") or ""
        concepts = llm.get("concepts") or []
        methods = llm.get("methods") or []
        results = llm.get("results") or []
        citations = llm.get("citations_mentioned") or []
        # 探针已采纳的原文抽取（来自 probe_cache adopted=True 条目）
        probe_excerpts = llm.get("probe_excerpts") or []

        parts = [f"# {title}\n"]
        if one_line:
            parts.append(f"> **一句话：** {one_line}\n")

        if summary:
            parts.append("## 中文摘要\n" + summary + "\n")

        if key_points:
            kp_lines = "\n".join(f"- {p}" for p in key_points)
            parts.append("## 关键点\n" + kp_lines + "\n")

        if abstract:
            parts.append("## 原始 Abstract\n" + abstract + "\n")

        has_extraction = concepts or methods or results or citations
        if has_extraction:
            parts.append("## 结构化抽取\n")

            if concepts:
                concept_lines = []
                for c in concepts:
                    if not isinstance(c, dict):
                        continue
                    name = c.get("name", "?")
                    ctype = c.get("type", "")
                    conf = c.get("confidence", "")
                    concept_lines.append(f"- **{name}** ({ctype}, 置信度 {conf})")
                if concept_lines:
                    parts.append("### 核心概念\n" + "\n".join(concept_lines) + "\n")

            if methods:
                method_lines = []
                for m in methods:
                    if not isinstance(m, dict):
                        continue
                    name = m.get("name", "?")
                    short = m.get("short", "")
                    method_lines.append(f"- **{name}** — {short}")
                if method_lines:
                    parts.append("### 方法\n" + "\n".join(method_lines) + "\n")

            if results:
                result_lines = []
                for r in results:
                    if not isinstance(r, dict):
                        continue
                    claim = r.get("claim", "?")
                    evidence = r.get("evidence", "")
                    result_lines.append(f"- {claim} ({evidence})")
                if result_lines:
                    parts.append("### 主要结果\n" + "\n".join(result_lines) + "\n")

            if citations:
                citation_lines = "\n".join(f"- {c}" for c in citations if isinstance(c, str))
                if citation_lines:
                    parts.append("### 提及的引文\n" + citation_lines + "\n")

        # ── 探针原文抽取（用户从协作/深度提取里采纳过的 section 级引用）──
        if probe_excerpts:
            parts.append("## 探针原文抽取\n")
            parts.append(
                "<sub>以下内容是用户在协作研究/深度分析中采纳的原文逐字引用，"
                "来自不同 section 的关键段落。</sub>\n"
            )
            for ex in probe_excerpts:
                if not isinstance(ex, dict):
                    continue
                label = ex.get("section_label") or f"段 {ex.get('section_idx', '?')}"
                relevance = ex.get("relevance") or 0
                insight = (ex.get("insight") or "").strip()
                quote = (ex.get("excerpt_quote") or "").strip()
                if not quote:
                    continue
                parts.append(f"### {label} <sup>(相关性 {relevance:.2f})</sup>")
                if insight:
                    parts.append(f"**要点：** {insight}\n")
                parts.append(f"> {quote}\n")

        # ── 用户笔记占位（M2 追加，为 M4 AI 重写保留用户手写区）──
        # AI 重写 md 时会扫描此段落并原样保留；用户可直接编辑
        parts.append(
            "## 用户笔记\n"
            "<!-- 用户手动编辑区 · AI 重写不会覆盖此段内容 -->\n"
        )

        # Footer
        source = doc.get("source") or "unknown"
        external = doc.get("external_id") or ""
        doi = doc.get("doi") or ""
        url = doc.get("url") or ""
        footer = (
            f"\n---\n<sub>来源: {source} {external} · "
            f"DOI: {doi} · [原文]({url}) · AI 自动生成</sub>\n"
        )
        parts.append(footer)

        return "\n".join(parts)

    @staticmethod
    def _split_authors(authors_raw: Any) -> list[str]:
        if not authors_raw:
            return []
        if isinstance(authors_raw, list):
            return [str(a).strip() for a in authors_raw if str(a).strip()]
        s = str(authors_raw)
        return [a.strip() for a in re.split(r"[;,]", s) if a.strip()][:20]

    @staticmethod
    def _extract_year(pub_date: Any) -> Optional[int]:
        if not pub_date:
            return None
        s = str(pub_date)
        m = re.match(r"(\d{4})", s)
        return int(m.group(1)) if m else None

    async def rebuild_index(self) -> None:
        """Scan literature/*.md, (re)write _index.md and .metadata/slug_map.json."""
        glob_result = await self.fs_glob.call(
            FsGlobInput(pattern="literature/*.md"),
            self.ctx,
        )
        entries: list[dict] = []
        for rel_path in glob_result.files:
            if rel_path.endswith("_index.md"):
                continue
            try:
                content = (
                    await self.fs_read.call(FsReadInput(path=rel_path), self.ctx)
                ).content
                fm, _ = parse_frontmatter(content)
                if fm:
                    entries.append(fm)
            except Exception as e:
                logger.warning("[LibWriter] skip broken md %s: %s", rel_path, e)

        index_md = self._render_index(entries)
        slug_map = self._build_slug_map(entries)

        await self.fs_write.call(
            FsWriteInput(path="literature/_index.md", content=index_md),
            self.ctx,
        )
        await self.fs_write.call(
            FsWriteInput(
                path="literature/.metadata/slug_map.json",
                content=json.dumps(slug_map, ensure_ascii=False, indent=2),
            ),
            self.ctx,
        )
        logger.info(
            "[LibWriter] index_rebuilt project=%s entries=%d",
            self.project_id[:8], len(entries),
        )

    # ------------------------------------------------------------------
    # Index template
    # ------------------------------------------------------------------

    def _render_index(self, entries: list[dict]) -> str:
        by_bucket: dict[str, list[dict]] = {
            "very_relevant": [],
            "relevant": [],
            "uncertain": [],
            "irrelevant": [],
            "uncategorized": [],
        }
        for e in entries:
            bucket = e.get("bucket") or "uncategorized"
            by_bucket.setdefault(bucket, []).append(e)

        counts = {k: len(v) for k, v in by_bucket.items() if v}
        total = sum(counts.values())

        fm = {
            "project_id": self.project_id,
            "total": total,
            "by_bucket": counts,
            "last_updated": _now_iso(),
        }
        fm_yaml = yaml.safe_dump(
            fm, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).rstrip()

        header = f"---\n{fm_yaml}\n---\n\n# 项目文献库 ({total} 篇)\n"

        section_labels = {
            "very_relevant": "Very Relevant",
            "relevant": "Relevant",
            "uncertain": "Uncertain",
            "irrelevant": "Irrelevant",
            "uncategorized": "Uncategorized",
        }
        sections: list[str] = []
        for key, label in section_labels.items():
            items = by_bucket.get(key) or []
            if not items:
                continue
            lines = [f"\n## {label} ({len(items)})\n"]
            for e in items:
                slug = e.get("slug") or "?"
                title = e.get("title") or "?"
                authors = e.get("authors") or []
                first_author = authors[0] if authors else ""
                plus = "+" if len(authors) > 1 else ""
                year = e.get("year") or ""
                citation = f"{first_author}{plus}, {year}" if first_author else f"{year}"
                lines.append(f"- [[{slug}]] — {title} ({citation})")
            sections.append("\n".join(lines))

        return header + "\n".join(sections) + "\n"

    def _build_slug_map(self, entries: list[dict]) -> dict:
        return {
            "version": 1,
            "project_id": self.project_id,
            "updated_at": _now_iso(),
            "entries": {
                e["id"]: {
                    "slug": e["slug"],
                    "bucket": e.get("bucket"),
                    "updated_at": e.get("updated_at"),
                }
                for e in entries
                if e.get("id") and e.get("slug")
            },
        }

    async def update_bucket(self, doc_id: str, new_bucket: Optional[str]) -> bool:
        """
        Sync a document's .md frontmatter bucket field with the DB value.
        Called by graph_tasks when the user reclassifies a document.

        Returns True if updated, False if the doc has no .md yet (e.g. not processed).
        """
        slug_map = await self._load_slug_map()
        entry = slug_map.get("entries", {}).get(str(doc_id))
        if not entry:
            return False
        slug = entry.get("slug")
        if not slug:
            return False
        rel_path = f"literature/{slug}.md"
        if not self.sandbox.exists(rel_path):
            return False
        text = (await self.fs_read.call(FsReadInput(path=rel_path), self.ctx)).content
        new_text = replace_frontmatter_field(text, "bucket", new_bucket)
        await self.fs_write.call(
            FsWriteInput(path=rel_path, content=new_text),
            self.ctx,
        )
        logger.info(
            "[LibWriter] bucket_sync project=%s doc=%s new=%s",
            self.project_id[:8], str(doc_id)[:8], new_bucket,
        )
        return True

    async def _load_slug_map(self) -> dict:
        """Load .metadata/slug_map.json, returning {} if missing."""
        rel_path = "literature/.metadata/slug_map.json"
        if not self.sandbox.exists(rel_path):
            return {}
        try:
            content = (
                await self.fs_read.call(FsReadInput(path=rel_path), self.ctx)
            ).content
            return json.loads(content)
        except Exception as e:
            logger.warning("[LibWriter] slug_map read failed: %s", e)
            return {}
