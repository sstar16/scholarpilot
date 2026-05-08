"""
Document Import Pipeline — 统一导入管线。

五种输入方式（DOI/URL/PDF/BibTeX/自然语言）最终都汇入 DOI 流程创建 Document。
用户上传的文档 source="user_upload"。
"""
import hashlib
import json
import logging
import re
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DOI_REGEX = re.compile(r'(10\.\d{4,}/\S+)')


async def import_by_doi(
    doi: str,
    project_id: str,
    user_id: str,
    bucket: str,
    db: AsyncSession,
) -> Optional[dict]:
    """
    Import a document by DOI. Core flow — all other modes converge here.

    Returns: {document_id, title, status, is_new} or None
    """
    from app.models.document import Document
    from app.models.document_classification import DocumentClassification

    doi = doi.strip().strip(".")

    # 1. Check existing by DOI
    existing = await db.execute(
        select(Document).where(Document.doi == doi)
    )
    doc = existing.scalar_one_or_none()

    if doc:
        # Already exists — just add classification
        await _ensure_classification(doc.id, project_id, user_id, bucket, db)
        return {"document_id": str(doc.id), "title": doc.title, "status": "imported", "is_new": False}

    # 2. Fetch metadata via CrossRef
    metadata = await _fetch_metadata_by_doi(doi)
    if not metadata:
        return None

    # 3. Create Document
    doc = Document(
        source="user_upload",
        external_id=doi,
        doc_type=metadata.get("doc_type", "paper"),
        title=metadata["title"],
        authors=metadata.get("authors"),
        abstract=metadata.get("abstract"),
        publication_date=metadata.get("publication_date"),
        url=metadata.get("url"),
        doi=doi,
        journal=metadata.get("journal"),
        citation_count=metadata.get("citation_count", 0),
        pdf_url=metadata.get("pdf_url"),
    )
    db.add(doc)
    await db.flush()

    # 4. Classify
    await _ensure_classification(doc.id, project_id, user_id, bucket, db)

    logger.info("[Import] DOI imported: %s → %s (%s)", doi, doc.title[:50], bucket)
    return {"document_id": str(doc.id), "title": doc.title, "status": "imported", "is_new": True}


async def import_by_url(
    url: str,
    project_id: str,
    user_id: str,
    bucket: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Import by URL. Extract DOI if possible, otherwise fetch page title."""
    # Try to extract DOI from URL
    doi_match = DOI_REGEX.search(url)
    if doi_match:
        return await import_by_doi(doi_match.group(1), project_id, user_id, bucket, db)

    # Try to fetch the page and find DOI in content
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                text = resp.text[:5000]
                doi_match = DOI_REGEX.search(text)
                if doi_match:
                    return await import_by_doi(doi_match.group(1), project_id, user_id, bucket, db)

                # Extract title from HTML
                title_match = re.search(r'<title>(.*?)</title>', text, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = title_match.group(1).strip()[:200]
                    return await _create_minimal_doc(
                        title=title, url=url, project_id=project_id,
                        user_id=user_id, bucket=bucket, db=db,
                    )
    except Exception as e:
        logger.warning("[Import] URL fetch failed: %s", e)

    return None


async def import_by_pdf(
    file_bytes: bytes,
    filename: str,
    project_id: str,
    user_id: str,
    bucket: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Import from uploaded PDF. Extract text, find DOI, create Document."""
    from app.services.fulltext_service import extract_text

    # Save PDF
    pdf_dir = Path("./data/pdfs") / project_id
    pdf_dir.mkdir(parents=True, exist_ok=True)
    file_hash = hashlib.md5(file_bytes[:4096]).hexdigest()[:12]
    pdf_path = pdf_dir / f"upload_{file_hash}.pdf"
    pdf_path.write_bytes(file_bytes)

    # Extract text — 全量抽取，section 级相关性判断交给下游 ProbeAgent
    text = await extract_text(str(pdf_path))
    if not text:
        return None

    # Try to find DOI in text
    doi_match = DOI_REGEX.search(text[:3000])
    if doi_match:
        result = await import_by_doi(doi_match.group(1), project_id, user_id, bucket, db)
        if result:
            # Update with fulltext since we already have it
            from app.models.document import Document
            from sqlalchemy import update
            await db.execute(
                update(Document).where(Document.id == uuid_mod.UUID(result["document_id"])).values(
                    fulltext_status="available",
                    fulltext_path=str(pdf_path),
                    fulltext_text=text[:150_000],
                )
            )
            await db.flush()
            return result

    # No DOI — extract metadata via LLM or heuristics
    metadata = await _extract_metadata_from_text(text[:3000], filename)

    from app.models.document import Document
    doc = Document(
        source="user_upload",
        external_id=f"pdf:{file_hash}",
        doc_type="paper",
        title=metadata.get("title", filename),
        authors=metadata.get("authors"),
        abstract=metadata.get("abstract"),
        fulltext_status="available",
        fulltext_path=str(pdf_path),
        fulltext_text=text[:150_000],
    )
    db.add(doc)
    await db.flush()

    await _ensure_classification(doc.id, project_id, user_id, bucket, db)

    logger.info("[Import] PDF imported: %s → %s (%d chars)", filename, doc.title[:50], len(text))
    return {"document_id": str(doc.id), "title": doc.title, "status": "imported", "is_new": True}


async def import_by_bibtex(
    bib_content: str,
    project_id: str,
    user_id: str,
    bucket: str,
    db: AsyncSession,
) -> list[dict]:
    """Import from BibTeX content. Returns list of import results."""
    try:
        import bibtexparser
    except ImportError:
        logger.error("[Import] bibtexparser not installed")
        return []

    try:
        library = bibtexparser.parse(bib_content)
    except Exception as e:
        logger.warning("[Import] BibTeX parse failed: %s", e)
        return []

    results = []
    for entry in library.entries:
        doi = entry.fields_dict.get("doi")
        doi_val = doi.value if doi else None
        title = entry.fields_dict.get("title")
        title_val = title.value if title else None

        if doi_val:
            result = await import_by_doi(doi_val, project_id, user_id, bucket, db)
            if result:
                results.append(result)
                continue

        # No DOI or DOI import failed — try title search
        if title_val:
            result = await _search_and_import(title_val, project_id, user_id, bucket, db)
            if result:
                results.append(result)
                continue

        # Create minimal doc from BibTeX fields
        if title_val:
            authors = entry.fields_dict.get("author")
            journal = entry.fields_dict.get("journal")
            result = await _create_minimal_doc(
                title=title_val,
                authors=authors.value if authors else None,
                journal=journal.value if journal else None,
                project_id=project_id,
                user_id=user_id,
                bucket=bucket,
                db=db,
            )
            if result:
                results.append(result)

    logger.info("[Import] BibTeX: %d entries → %d imported", len(library.entries), len(results))
    return results


async def import_by_natural_language(
    query: str,
    project_id: str,
    user_id: str,
    bucket: str,
    db: AsyncSession,
) -> Optional[list[dict]]:
    """
    Search for documents matching natural language description.
    Returns candidate list for user confirmation (not auto-imported).
    """
    # Extract DOI if present
    doi_match = DOI_REGEX.search(query)
    if doi_match:
        result = await import_by_doi(doi_match.group(1), project_id, user_id, bucket, db)
        return [result] if result else None

    # Search existing documents in DB
    candidates = await _search_existing_docs(query, db)

    # Search local KB
    if not candidates:
        candidates = await _search_local_kb(query)

    # Search CrossRef
    if not candidates:
        candidates = await _search_crossref(query)

    return candidates if candidates else None


# ──────────── Internal Helpers ────────────

async def _fetch_metadata_by_doi(doi: str) -> Optional[dict]:
    """Fetch metadata from CrossRef, fallback to OpenAlex."""
    try:
        import httpx
        # CrossRef
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.crossref.org/works/{doi}",
                headers={"User-Agent": "ScholarPilot/1.0 (mailto:scholarpilot@example.com)"},
            )
            if resp.status_code == 200:
                item = resp.json().get("message", {})
                title_parts = item.get("title", [])
                title = title_parts[0] if title_parts else None
                if not title:
                    return None

                authors = "; ".join(
                    f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in item.get("author", [])[:10]
                )

                # Publication date
                pub_date = None
                date_parts = item.get("published-print", item.get("published-online", {})).get("date-parts", [[]])
                if date_parts and date_parts[0]:
                    parts = date_parts[0]
                    try:
                        from datetime import date
                        pub_date = date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
                    except (ValueError, IndexError):
                        pass

                abstract = item.get("abstract", "")
                if abstract:
                    abstract = re.sub(r'<[^>]+>', '', abstract)[:2000]

                # PDF link
                links = item.get("link", [])
                pdf_url = None
                for link in links:
                    if "pdf" in link.get("content-type", ""):
                        pdf_url = link.get("URL")
                        break

                return {
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "publication_date": pub_date,
                    "url": item.get("URL"),
                    "journal": item.get("container-title", [""])[0] if item.get("container-title") else None,
                    "citation_count": item.get("is-referenced-by-count", 0),
                    "pdf_url": pdf_url,
                    "doc_type": "paper",
                }
    except Exception as e:
        logger.warning("[Import] CrossRef lookup failed for %s: %s", doi, e)

    # OpenAlex fallback
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"https://api.openalex.org/works/doi:{doi}")
            if resp.status_code == 200:
                item = resp.json()
                return {
                    "title": item.get("title", ""),
                    "authors": "; ".join(a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])[:10]),
                    "abstract": "",
                    "publication_date": None,
                    "url": item.get("doi"),
                    "journal": (item.get("primary_location") or {}).get("source", {}).get("display_name"),
                    "citation_count": item.get("cited_by_count", 0),
                    "pdf_url": (item.get("best_oa_location") or {}).get("pdf_url"),
                    "doc_type": "paper",
                }
    except Exception as e:
        logger.warning("[Import] OpenAlex lookup failed for %s: %s", doi, e)

    return None


async def _extract_metadata_from_text(text: str, filename: str) -> dict:
    """Extract title/authors/abstract from PDF text, LLM or heuristic."""
    # Heuristic: first non-empty line as title, look for "Abstract" section
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0] if lines else filename

    # Find abstract
    abstract = ""
    for i, line in enumerate(lines):
        if re.match(r'^abstract\b', line, re.IGNORECASE):
            abstract_lines = []
            for j in range(i + 1, min(i + 10, len(lines))):
                if re.match(r'^(introduction|keywords|1\.)', lines[j], re.IGNORECASE):
                    break
                abstract_lines.append(lines[j])
            abstract = " ".join(abstract_lines)[:1000]
            break

    # Try LLM extraction if available
    try:
        from app.services.core.llm_config_store import get_llm_manager
        manager = await get_llm_manager()
        prompt = f"""从以下PDF文本开头提取论文元数据。仅输出JSON：
{{"title": "...", "authors": "作者1; 作者2", "abstract": "摘要前200字"}}

文本：
{text[:2000]}"""
        result = await manager.generate(
            prompt, temperature=0.1,
            response_format={"type": "json_object"},
        )
        if result:
            match = re.search(r'\{[\s\S]*"title"[\s\S]*\}', result)
            if match:
                data = json.loads(match.group())
                return {
                    "title": data.get("title", title)[:200],
                    "authors": data.get("authors"),
                    "abstract": data.get("abstract", abstract)[:1000],
                }
    except Exception:
        pass

    return {"title": title[:200], "authors": None, "abstract": abstract}


async def _ensure_classification(
    document_id, project_id: str, user_id: str, bucket: str, db: AsyncSession,
):
    """Create or update DocumentClassification."""
    from app.models.document_classification import DocumentClassification

    pid = uuid_mod.UUID(project_id) if isinstance(project_id, str) else project_id
    uid = uuid_mod.UUID(user_id) if isinstance(user_id, str) else user_id
    did = document_id if isinstance(document_id, uuid_mod.UUID) else uuid_mod.UUID(str(document_id))

    existing = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == uid,
            DocumentClassification.project_id == pid,
            DocumentClassification.document_id == did,
        )
    )
    cls = existing.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if cls:
        cls.bucket = bucket
        cls.moved_at = now
    else:
        cls = DocumentClassification(
            user_id=uid,
            project_id=pid,
            document_id=did,
            bucket=bucket,
            classified_at=now,
        )
        db.add(cls)
    await db.flush()


async def _create_minimal_doc(
    title: str, project_id: str, user_id: str, bucket: str, db: AsyncSession,
    url: str = None, authors: str = None, journal: str = None,
) -> Optional[dict]:
    """Create a Document with minimal metadata."""
    from app.models.document import Document

    content_hash = hashlib.md5(title.lower().encode()).hexdigest()

    # Check duplicate by title hash
    existing = await db.execute(
        select(Document).where(Document.content_hash == content_hash)
    )
    doc = existing.scalar_one_or_none()
    if doc:
        await _ensure_classification(doc.id, project_id, user_id, bucket, db)
        return {"document_id": str(doc.id), "title": doc.title, "status": "imported", "is_new": False}

    doc = Document(
        source="user_upload",
        external_id=f"manual:{content_hash[:16]}",
        doc_type="paper",
        title=title[:200],
        authors=authors,
        journal=journal,
        url=url,
        content_hash=content_hash,
    )
    db.add(doc)
    await db.flush()
    await _ensure_classification(doc.id, project_id, user_id, bucket, db)
    return {"document_id": str(doc.id), "title": doc.title, "status": "imported", "is_new": True}


async def _search_and_import(
    title: str, project_id: str, user_id: str, bucket: str, db: AsyncSession,
) -> Optional[dict]:
    """Search CrossRef by title, import first match."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.crossref.org/works",
                params={"query.title": title, "rows": 1},
                headers={"User-Agent": "ScholarPilot/1.0"},
            )
            if resp.status_code == 200:
                items = resp.json().get("message", {}).get("items", [])
                if items:
                    doi = items[0].get("DOI")
                    if doi:
                        return await import_by_doi(doi, project_id, user_id, bucket, db)
    except Exception as e:
        logger.warning("[Import] CrossRef title search failed: %s", e)
    return None


async def _search_existing_docs(query: str, db: AsyncSession) -> list[dict]:
    """Search existing Document table by title keyword."""
    from app.models.document import Document
    keywords = [w for w in query.split() if len(w) >= 2][:5]
    if not keywords:
        return []

    # Simple ILIKE search
    from sqlalchemy import or_
    conditions = [Document.title.ilike(f"%{kw}%") for kw in keywords]
    result = await db.execute(
        select(Document).where(or_(*conditions)).limit(5)
    )
    docs = result.scalars().all()
    return [
        {"document_id": str(d.id), "title": d.title, "doi": d.doi, "source": d.source}
        for d in docs
    ]


async def _search_local_kb(query: str) -> list[dict]:
    """Search local knowledge base."""
    try:
        from app.knowledge_base.search_index import SearchIndex
        from app.knowledge_base.config import KB_SEARCH_DB
        if not Path(KB_SEARCH_DB).exists():
            return []
        idx = SearchIndex(Path(KB_SEARCH_DB))
        results = idx.search(query, limit=5)
        return [
            {"external_id": r["openalex_id"], "title": r.get("title", ""), "source": "local_kb"}
            for r in results
        ]
    except Exception:
        return []


async def _search_crossref(query: str) -> list[dict]:
    """Search CrossRef by query."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.crossref.org/works",
                params={"query": query, "rows": 5},
                headers={"User-Agent": "ScholarPilot/1.0"},
            )
            if resp.status_code == 200:
                items = resp.json().get("message", {}).get("items", [])
                return [
                    {
                        "doi": item.get("DOI"),
                        "title": (item.get("title") or [""])[0],
                        "source": "crossref",
                    }
                    for item in items if item.get("title")
                ]
    except Exception:
        pass
    return []
