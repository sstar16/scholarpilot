"""
Lens.org Patent API -> 本地知识库

用法:
  python scripts/kb_etl/download_lens_patents.py \
    --keywords "flavor capsule" "crush capsule" "flavor ball" "tobacco bead" "heat-not-burn" \
    --output data/kb_tobacco
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.knowledge_base.metadata_store import MetadataStore
from backend.app.knowledge_base.search_index import SearchIndex
from backend.app.knowledge_base.relations import RelationStore
from backend.app.knowledge_base.config import ABSTRACT_PREVIEW_MAX_CHARS

LENS_API = "https://api.lens.org/patent/search"
LENS_TOKEN = os.environ.get("LENS_API_TOKEN", "")
PAGE_SIZE = 100
REQUEST_DELAY = 1.0  # Lens rate limit


def search_lens(keywords: list[str], min_year: int | None, existing_ids: set[str]) -> list[dict]:
    """Lens Patent API 搜索，返回 KB 格式的专利列表"""
    if not LENS_TOKEN:
        print("[ERROR] LENS_API_TOKEN not set")
        return []

    headers = {
        "Authorization": f"Bearer {LENS_TOKEN}",
        "Content-Type": "application/json",
    }

    # 简单 query string（Lens 不支持 field:>= 语法，日期用后过滤）
    query_str = " OR ".join(f'"{kw}"' for kw in keywords)

    query_body = {
        "query": query_str,
        "size": PAGE_SIZE,
        "from": 0,
        "include": [
            "lens_id", "jurisdiction", "doc_number", "kind",
            "biblio", "abstract", "date_published",
        ],
    }

    all_patents = []
    offset = 0
    total = None

    client = httpx.Client(verify=False, timeout=30)

    while True:
        query_body["from"] = offset

        try:
            resp = client.post(LENS_API, json=query_body, headers=headers)
            if resp.status_code == 429:
                print("  Rate limited, waiting 10s...")
                time.sleep(10)
                continue
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"  [ERROR] Lens API: {e}")
            break

        data = resp.json()
        results = data.get("data", [])
        if total is None:
            total = data.get("total", 0)
            print(f"  Lens found {total:,} patents")

        if not results:
            break

        for pat in results:
            lens_id = pat.get("lens_id", "")
            kb_id = f"LENS:{lens_id}"

            if kb_id in existing_ids:
                continue

            # 年份后过滤
            date_pub = pat.get("date_published", "")
            year = int(date_pub[:4]) if date_pub and len(date_pub) >= 4 else None
            if min_year and year and year < min_year:
                continue

            jurisdiction = pat.get("jurisdiction", "")
            doc_number = pat.get("doc_number", "")
            kind = pat.get("kind", "")
            pub_ref = f"{jurisdiction}{doc_number}{kind}"

            biblio = pat.get("biblio") or {}

            # Title from biblio.invention_title
            title = ""
            for t in (biblio.get("invention_title") or []):
                if t.get("lang") == "en":
                    title = t.get("text", "")
                    break
            if not title:
                titles = biblio.get("invention_title") or []
                title = titles[0].get("text", "") if titles else pub_ref

            # Abstract
            abstract_text = ""
            for a in (pat.get("abstract") or []):
                if a.get("lang") == "en":
                    abstract_text = a.get("text", "")
                    break
            if not abstract_text:
                abstracts = pat.get("abstract") or []
                abstract_text = abstracts[0].get("text", "") if abstracts else ""

            # Parties from biblio.parties
            parties = biblio.get("parties") or {}

            applicants = []
            for app in (parties.get("applicants") or [])[:5]:
                name = (app.get("extracted_name") or {}).get("value", "")
                if name:
                    applicants.append(name)

            inventors = []
            for inv in (parties.get("inventors") or [])[:5]:
                name = (inv.get("extracted_name") or {}).get("value", "")
                if name:
                    inventors.append(name)

            # IPC from biblio.classifications_ipc
            ipc_codes = []
            for c in (biblio.get("classifications_ipc") or {}).get("classifications", [])[:5]:
                code = c.get("symbol", "")
                if code:
                    ipc_codes.append(code)

            all_patents.append({
                "openalex_id": kb_id,
                "doi": None,
                "title": title or pub_ref,
                "publication_year": year,
                "publication_date": date_pub,
                "language": "en",
                "type": "patent",
                "cited_by_count": 0,
                "authors": "; ".join(inventors) if inventors else "; ".join(applicants),
                "source_name": "; ".join(applicants) if applicants else f"{jurisdiction} Patent",
                "source_issn": None,
                "abstract_preview": abstract_text[:ABSTRACT_PREVIEW_MAX_CHARS] if abstract_text else None,
                "primary_topic_id": ipc_codes[0] if ipc_codes else None,
                "primary_topic_name": "; ".join(ipc_codes) if ipc_codes else None,
                "primary_field_name": "Patent",
                "primary_domain_name": "Patent",
                "countries": jurisdiction,
                "is_oa": False,
                "pdf_url": None,
                "landing_url": f"https://www.lens.org/lens/patent/{lens_id}",
            })

        offset += len(results)
        if offset >= min(total, 10000):  # Lens 免费上限
            break

        if offset % 500 == 0:
            print(f"    ... {offset:,} / {total:,}")

        time.sleep(REQUEST_DELAY)

    client.close()
    print(f"  Fetched {len(all_patents):,} new patents (deduped)")
    return all_patents


def run(keywords: list[str], output_dir: Path, min_year: int | None):
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = MetadataStore(output_dir / "metadata.duckdb")
    search = SearchIndex(output_dir / "search.sqlite")
    relations = RelationStore(output_dir / "relations.sqlite")
    metadata.init_schema()
    search.init_schema()
    relations.init_schema()

    # 获取已有 ID 用于去重（复用 MetadataStore 的连接）
    import duckdb
    conn = metadata._get_conn() if hasattr(metadata, '_get_conn') else duckdb.connect(str(output_dir / "metadata.duckdb"))
    existing = set(r[0] for r in conn.execute("SELECT openalex_id FROM works").fetchall())
    print(f"Existing KB: {len(existing):,} docs")

    print(f"\n>> Lens.org Patent Search")
    patents = search_lens(keywords, min_year, existing)

    if patents:
        print(f"\n>> Writing {len(patents):,} patents to KB...")
        metadata.bulk_insert(patents)
        search.bulk_index(patents)

        topic_triples = []
        for p in patents:
            if p["primary_topic_id"]:
                topic_triples.append((p["openalex_id"], p["primary_topic_id"][:4], 1.0))
        if topic_triples:
            relations.bulk_insert_topics(topic_triples)

        search.optimize()
        print(f"[DONE] {len(patents):,} Lens patents added. Total KB: {metadata.count():,}")
    else:
        print("No new patents from Lens.")

    metadata.close()
    search.close()
    relations.close()


def main():
    parser = argparse.ArgumentParser(description="Lens.org patent download -> KB")
    parser.add_argument("--keywords", nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=Path("data/kb_tobacco"))
    parser.add_argument("--min-year", type=int, default=None)
    args = parser.parse_args()
    run(args.keywords, args.output, args.min_year)


if __name__ == "__main__":
    main()
