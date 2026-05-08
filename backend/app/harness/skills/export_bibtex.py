"""
Export BibTeX Skill — 一键把项目文献库导出为 BibTeX (.bib) 格式

零 LLM 成本，全本地计算。
输入：project_id
输出：{"bibtex": "...", "count": N, "filename": "scholarpilot-<slug>.bib"}

字段映射：
  Document.doi      → doi
  Document.title    → title
  Document.authors  → author (" and " 连接)
  Document.journal  → journal
  year              → 取 publication_date 年份
  Document.abstract → abstract（可选，超长文献会裁切）

支持的条目类型（按 doc_type 推断）：
  paper        → @article
  preprint     → @unpublished
  patent       → @misc
  default      → @misc
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from app.harness.skill_registry import SkillDefinition, SkillTrigger

logger = logging.getLogger(__name__)

DEFINITION = SkillDefinition(
    skill_id="export_bibtex",
    display_name="Export BibTeX",
    description="把当前项目的文献库导出为 BibTeX (.bib) 格式",
    trigger=SkillTrigger.USER_ACTION,
    required_context=["project_id"],
    estimated_llm_calls=0,
    estimated_duration_seconds=2,
    min_round=1,
)


async def execute(context: Dict[str, Any]) -> Dict[str, Any]:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy import select
    from app.config import settings
    from app.models.document import Document
    from app.models.round_document import RoundDocument
    from app.models.document_classification import DocumentClassification
    from app.models.search_round import SearchRound
    from app.models.project import Project

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as db:
            project = await db.get(Project, context["project_id"])
            if not project:
                return {"error": "Project not found"}

            # 项目文献 = (本项目所有 round 下的所有 RoundDocument) ∪ (DocumentClassification 里的 doc)
            # 后者覆盖手动上传的文档
            round_ids_q = await db.execute(
                select(SearchRound.id).where(SearchRound.project_id == project.id)
            )
            round_ids = [r[0] for r in round_ids_q.all()]

            doc_ids: set = set()
            if round_ids:
                q = await db.execute(
                    select(RoundDocument.document_id).where(
                        RoundDocument.round_id.in_(round_ids)
                    )
                )
                doc_ids.update(r[0] for r in q.all())

            q2 = await db.execute(
                select(DocumentClassification.document_id).where(
                    DocumentClassification.project_id == project.id
                )
            )
            doc_ids.update(r[0] for r in q2.all())

            if not doc_ids:
                return {"error": "项目下暂无文献"}

            docs_q = await db.execute(
                select(Document).where(Document.id.in_(doc_ids))
            )
            docs = list(docs_q.scalars().all())

            entries = [_to_bibtex(d) for d in docs]
            bibtex_text = "\n\n".join(entries)
            slug = _slugify(project.title or str(project.id)[:8])

            return {
                "bibtex": bibtex_text,
                "count": len(entries),
                "filename": f"scholarpilot-{slug}.bib",
                "project_title": project.title,
            }
    finally:
        await engine.dispose()


def _to_bibtex(doc) -> str:
    entry_type = {
        "paper": "article",
        "preprint": "unpublished",
        "patent": "misc",
    }.get(getattr(doc, "doc_type", None) or "paper", "misc")

    key = _make_cite_key(doc)
    fields: List[str] = []
    if doc.title:
        fields.append(_field("title", doc.title))
    if doc.authors:
        fields.append(_field("author", _join_authors(doc.authors)))
    year = _year_from(doc)
    if year:
        fields.append(f"  year = {{{year}}}")
    if doc.journal:
        fields.append(_field("journal", doc.journal))
    if doc.doi:
        fields.append(_field("doi", doc.doi))
    if doc.url:
        fields.append(_field("url", doc.url))
    # abstract: 截断避免过长；BibTeX 不强制，但有些阅读工具（JabRef）会用
    abs_text = (doc.abstract or "")[:1000]
    if abs_text:
        fields.append(_field("abstract", abs_text))

    body = ",\n".join(fields)
    return f"@{entry_type}{{{key},\n{body}\n}}"


def _make_cite_key(doc) -> str:
    """Author_year_keyword 风格的 cite key。用 slug 过滤特殊字符。"""
    first_author = ""
    if doc.authors:
        first_author = doc.authors.split(",")[0].split("；")[0].strip().split()[-1] if doc.authors.strip() else ""
        first_author = _slugify(first_author or "anon")
    year = _year_from(doc) or "n.d."
    first_word = ""
    if doc.title:
        words = re.split(r"\s+", doc.title.strip())
        for w in words:
            cleaned = _slugify(w)
            if cleaned and len(cleaned) > 2:
                first_word = cleaned
                break
    parts = [p for p in [first_author, str(year), first_word] if p]
    key = "_".join(parts) or f"doc_{str(doc.id)[:8]}"
    return key[:40]


def _year_from(doc) -> int | None:
    if doc.publication_date:
        try:
            return doc.publication_date.year
        except Exception:
            pass
    return None


def _join_authors(raw: str) -> str:
    # 尝试多种分隔符：',' / ';' / '；' / ' and '
    parts = re.split(r"[,;；]| and ", raw)
    return " and ".join(p.strip() for p in parts if p.strip())


def _field(name: str, value: str) -> str:
    # BibTeX 需要转义 {}, 且字段值用 {} 包裹避免大小写被自动小写
    safe = value.replace("{", r"\{").replace("}", r"\}")
    return f"  {name} = {{{safe}}}"


def _slugify(text: str) -> str:
    # 保留 ASCII 字母数字，其他转下划线
    out = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return out.lower()[:30]
