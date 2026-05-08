"""
EPO Open Patent Services -> 本地知识库

按 IPC 分类号批量下载专利（A24D = 烟草滤嘴/爆珠）

用法:
  python scripts/kb_etl/download_epo_patents.py \
    --ipc "A24D3" "A24B15" "A24F47" \
    --keywords "capsule" "bead" "flavor" \
    --output data/kb_tobacco
"""
import argparse
import os
import sys
import time
import base64
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.knowledge_base.metadata_store import MetadataStore
from backend.app.knowledge_base.search_index import SearchIndex
from backend.app.knowledge_base.relations import RelationStore
from backend.app.knowledge_base.config import ABSTRACT_PREVIEW_MAX_CHARS

EPO_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"
EPO_BIBLIO_URL = "https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc"

EPO_KEY = os.environ.get("EPO_CONSUMER_KEY", "")
EPO_SECRET = os.environ.get("EPO_CONSUMER_SECRET", "")

REQUEST_DELAY = 0.6  # EPO 允许 ~2 req/s


def get_epo_token(client: httpx.Client) -> str | None:
    if not EPO_KEY or not EPO_SECRET:
        print("[ERROR] EPO_CONSUMER_KEY / EPO_CONSUMER_SECRET not set")
        return None

    auth_str = base64.b64encode(f"{EPO_KEY}:{EPO_SECRET}".encode()).decode()
    resp = client.post(
        EPO_AUTH_URL,
        headers={"Authorization": f"Basic {auth_str}"},
        data={"grant_type": "client_credentials"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_epo(
    ipc_codes: list[str],
    keywords: list[str],
    min_year: int | None,
    existing_ids: set[str],
    client: httpx.Client,
    token: str,
) -> list[dict]:
    """EPO OPS 检索，返回 KB 格式的专利"""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    all_patents = []

    for ipc in ipc_codes:
        # 构建 CQL 查询: ipc=A24D3 AND (ti=capsule OR ti=bead OR ti=flavor)
        kw_part = " OR ".join([f'ti="{kw}"' for kw in keywords])
        cql = f'ipc="{ipc}" AND ({kw_part})'
        if min_year:
            cql += f' AND pd>={min_year}0101'

        print(f"  >> EPO: {cql[:80]}...")

        start = 1
        total = None

        while True:
            end = start + 99  # EPO max 100 per page
            params = {"q": cql, "Range": f"{start}-{end}"}

            try:
                resp = client.get(EPO_SEARCH_URL, params=params, headers=headers, timeout=30)
                if resp.status_code == 404:
                    print(f"     No results for IPC {ipc}")
                    break
                if resp.status_code == 403:
                    print(f"     Rate limited, waiting 60s...")
                    time.sleep(60)
                    token = get_epo_token(client)
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                resp.raise_for_status()
            except httpx.HTTPError as e:
                print(f"     [ERROR] EPO: {e}")
                break

            data = resp.json()
            search_result = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {})

            if total is None:
                total_str = search_result.get("@total-result-count", "0")
                total = int(total_str)
                print(f"     Found {total:,} results for IPC {ipc}")

            results = search_result.get("ops:search-result", {}).get("ops:publication-reference", [])
            if not results:
                break
            if not isinstance(results, list):
                results = [results]

            for pub_ref in results:
                doc_id = pub_ref.get("document-id", {})
                if isinstance(doc_id, list):
                    doc_id = doc_id[0]

                country = doc_id.get("country", {}).get("$", "")
                doc_number = doc_id.get("doc-number", {}).get("$", "")
                kind = doc_id.get("kind", {}).get("$", "")
                pub_num = f"{country}{doc_number}{kind}"
                kb_id = f"EPO:{pub_num}"

                if kb_id in existing_ids:
                    continue

                all_patents.append({
                    "openalex_id": kb_id,
                    "doi": None,
                    "title": pub_num,  # Will be enriched later
                    "publication_year": None,
                    "publication_date": None,
                    "language": "en",
                    "type": "patent",
                    "cited_by_count": 0,
                    "authors": "",
                    "source_name": f"{country} Patent",
                    "source_issn": None,
                    "abstract_preview": None,
                    "primary_topic_id": ipc,
                    "primary_topic_name": ipc,
                    "primary_field_name": "Patent",
                    "primary_domain_name": "Patent",
                    "countries": country,
                    "is_oa": False,
                    "pdf_url": None,
                    "landing_url": f"https://worldwide.espacenet.com/patent/search?q={pub_num}",
                    # 暂存用于后续 enrichment
                    "_epo_country": country,
                    "_epo_doc_number": doc_number,
                    "_epo_kind": kind,
                })
                existing_ids.add(kb_id)

            start += len(results)
            if start > min(total, 2000):  # EPO 限制
                break
            time.sleep(REQUEST_DELAY)

    print(f"  Total EPO hits: {len(all_patents):,} new patents")
    return all_patents


def enrich_patents(patents: list[dict], client: httpx.Client, token: str) -> list[dict]:
    """批量获取 EPO 专利的 title + abstract"""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    enriched = 0
    for i, pat in enumerate(patents):
        country = pat.pop("_epo_country", "")
        doc_number = pat.pop("_epo_doc_number", "")
        kind = pat.pop("_epo_kind", "")

        if not doc_number:
            continue

        url = f"{EPO_BIBLIO_URL}/{country}.{doc_number}.{kind}/biblio"
        try:
            resp = client.get(url, headers=headers, timeout=15)
            if resp.status_code == 403:
                time.sleep(60)
                token = get_epo_token(client)
                headers["Authorization"] = f"Bearer {token}"
                resp = client.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue

            data = resp.json()
            exch = data.get("ops:world-patent-data", {}).get("exchange-documents", {}).get("exchange-document", {})
            if isinstance(exch, list):
                exch = exch[0]

            # Title
            biblio = exch.get("bibliographic-data", {})
            titles = biblio.get("invention-title", [])
            if not isinstance(titles, list):
                titles = [titles]
            for t in titles:
                if t.get("@lang") == "en":
                    pat["title"] = t.get("$", pat["title"])
                    break
            if pat["title"] == f"{country}{doc_number}{kind}" and titles:
                pat["title"] = titles[0].get("$", pat["title"])

            # Abstract
            abstracts = exch.get("abstract", [])
            if not isinstance(abstracts, list):
                abstracts = [abstracts]
            for a in abstracts:
                if a.get("@lang") == "en":
                    p_tag = a.get("p", {})
                    text = p_tag.get("$", "") if isinstance(p_tag, dict) else str(p_tag)
                    pat["abstract_preview"] = text[:ABSTRACT_PREVIEW_MAX_CHARS]
                    break

            # Date
            pub_ref = biblio.get("publication-reference", {}).get("document-id", [])
            if isinstance(pub_ref, list):
                for d in pub_ref:
                    date_str = d.get("date", {}).get("$", "")
                    if date_str and len(date_str) >= 8:
                        pat["publication_date"] = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                        pat["publication_year"] = int(date_str[:4])
                        break

            # Applicants
            applicants = biblio.get("parties", {}).get("applicants", {}).get("applicant", [])
            if not isinstance(applicants, list):
                applicants = [applicants]
            names = []
            for app in applicants[:5]:
                name_data = app.get("applicant-name", {}).get("name", {})
                name = name_data.get("$", "") if isinstance(name_data, dict) else str(name_data)
                if name:
                    names.append(name)
            if names:
                pat["source_name"] = "; ".join(names)

            enriched += 1
        except Exception:
            pass

        if (i + 1) % 50 == 0:
            print(f"    Enriched {i + 1}/{len(patents)}...")
        time.sleep(REQUEST_DELAY)

    print(f"  Enriched {enriched}/{len(patents)} patents with title/abstract")
    return patents


def run(ipc_codes: list[str], keywords: list[str], output_dir: Path, min_year: int | None):
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = MetadataStore(output_dir / "metadata.duckdb")
    search = SearchIndex(output_dir / "search.sqlite")
    relations = RelationStore(output_dir / "relations.sqlite")
    metadata.init_schema()
    search.init_schema()
    relations.init_schema()

    import duckdb
    conn = metadata._get_conn() if hasattr(metadata, '_get_conn') else duckdb.connect(str(output_dir / "metadata.duckdb"))
    existing = set(r[0] for r in conn.execute("SELECT openalex_id FROM works").fetchall())
    print(f"Existing KB: {len(existing):,} docs")

    client = httpx.Client(verify=False)
    token = get_epo_token(client)
    if not token:
        return

    print(f"\n>> EPO OPS Patent Search")
    patents = search_epo(ipc_codes, keywords, min_year, existing, client, token)

    if patents:
        print(f"\n>> Enriching {len(patents):,} patents...")
        patents = enrich_patents(patents, client, token)

        print(f"\n>> Writing to KB...")
        metadata.bulk_insert(patents)
        search.bulk_index(patents)

        topic_triples = [(p["openalex_id"], p["primary_topic_id"][:4], 1.0) for p in patents if p.get("primary_topic_id")]
        if topic_triples:
            relations.bulk_insert_topics(topic_triples)

        search.optimize()
        print(f"[DONE] {len(patents):,} EPO patents added. Total KB: {metadata.count():,}")
    else:
        print("No new patents from EPO.")

    client.close()
    metadata.close()
    search.close()
    relations.close()


def main():
    parser = argparse.ArgumentParser(description="EPO OPS patent download -> KB")
    parser.add_argument("--ipc", nargs="+", default=["A24D3", "A24B15", "A24F47"])
    parser.add_argument("--keywords", nargs="+", default=["capsule", "bead", "flavor", "burst"])
    parser.add_argument("--output", type=Path, default=Path("data/kb_tobacco"))
    parser.add_argument("--min-year", type=int, default=None)
    args = parser.parse_args()
    run(args.ipc, args.keywords, args.output, args.min_year)


if __name__ == "__main__":
    main()
