"""
BigQuery 中国专利批量下载 -> 本地知识库

用法:
  # 下载烟草爆珠相关专利
  python scripts/kb_etl/download_bigquery_patents.py \
    --keywords "爆珠" "烟用香珠" "香味胶囊" "破碎珠" "滤嘴珠" \
    --output data/kb_tobacco

  # 自定义查询（直接写 SQL WHERE 片段）
  python scripts/kb_etl/download_bigquery_patents.py \
    --where "title_info.text LIKE '%烟草%' AND abstract_info.text LIKE '%爆珠%'" \
    --output data/kb_tobacco

前置:
  1. GOOGLE_APPLICATION_CREDENTIALS 环境变量指向 service account JSON
  2. pip install google-cloud-bigquery
  3. 国内需代理: set https_proxy=http://127.0.0.1:7890 (或在 .env 中配置)

成本估算:
  patents.publications 全表 ~120GB
  单次 LIKE 查询扫描 ~50-100GB ≈ $0.25-0.50
  烟草爆珠相关专利预估 500-3000 条
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.knowledge_base.metadata_store import MetadataStore
from backend.app.knowledge_base.search_index import SearchIndex
from backend.app.knowledge_base.relations import RelationStore
from backend.app.knowledge_base.config import ABSTRACT_PREVIEW_MAX_CHARS


def format_date(date_int) -> str | None:
    if not date_int:
        return None
    s = str(date_int)
    if len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def extract_year(date_int) -> int | None:
    if not date_int:
        return None
    s = str(date_int)
    if len(s) >= 4:
        return int(s[:4])
    return None


def extract_names(harmonized) -> str:
    if not harmonized:
        return ""
    names = []
    items = harmonized if isinstance(harmonized, list) else [harmonized]
    for item in items[:10]:
        if isinstance(item, dict):
            name = item.get("name", "")
        elif isinstance(item, str):
            name = item
        else:
            continue
        if name:
            names.append(name)
    return "; ".join(names)


def build_keyword_sql(keywords: list[str]) -> str:
    """从关键词列表生成 WHERE 子句"""
    conditions = []
    for kw in keywords:
        escaped = kw.replace("'", "\\'")
        conditions.append(
            f"(title_info.text LIKE '%{escaped}%' OR abstract_info.text LIKE '%{escaped}%')"
        )
    return " OR ".join(conditions)


def query_bigquery(keywords: list[str] = None, where_clause: str = None, min_year: int = None, lang: str = "zh", country: str = "CN") -> list[dict]:
    """执行 BigQuery 查询，返回专利列表。lang: zh/en, country: CN 或 * 表示全部"""
    from google.cloud import bigquery

    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if cred_path and os.path.exists(cred_path):
        client = bigquery.Client.from_service_account_json(cred_path)
    else:
        print("[ERROR] GOOGLE_APPLICATION_CREDENTIALS not set or file not found")
        print(f"  Current value: {cred_path}")
        return []

    # 构建 WHERE
    if where_clause:
        content_filter = where_clause
    elif keywords:
        content_filter = build_keyword_sql(keywords)
    else:
        print("[ERROR] Must specify --keywords or --where")
        return []

    date_filter = ""
    if min_year:
        date_filter = f"AND pub.publication_date >= {min_year}0101"

    country_filter = f"pub.country_code = '{country}'" if country != "*" else "1=1"

    sql = f"""
    SELECT
      pub.publication_number,
      pub.publication_date,
      pub.filing_date,
      pub.family_id,
      title_info.text AS title_zh,
      abstract_info.text AS abstract_zh,
      pub.inventor_harmonized,
      pub.assignee_harmonized,
      pub.ipc
    FROM
      `patents-public-data.patents.publications` AS pub,
      UNNEST(title_localized) AS title_info,
      UNNEST(abstract_localized) AS abstract_info
    WHERE
      {country_filter}
      AND title_info.language = '{lang}'
      AND abstract_info.language = '{lang}'
      AND abstract_info.text IS NOT NULL
      AND ({content_filter})
      {date_filter}
    """

    print(f">> Querying BigQuery...")
    print(f"   Filter: {content_filter[:100]}...")
    t0 = time.time()

    try:
        job = client.query(sql)
        rows = list(job)
        gb = (job.total_bytes_processed or 0) / 1e9
        cost = gb * 5.0 / 1000  # $5 per TB
        elapsed = time.time() - t0
        print(f"   Results: {len(rows):,} patents")
        print(f"   Scanned: {gb:.2f} GB (est. cost: ${cost:.3f})")
        print(f"   Time: {elapsed:.1f}s")
    except Exception as e:
        print(f"[ERROR] BigQuery query failed: {e}")
        return []

    # 转为 KB 格式
    patents = []
    seen = set()
    for row in rows:
        pub_num = row.publication_number or ""
        if not pub_num or pub_num in seen:
            continue
        seen.add(pub_num)

        title = row.title_zh or pub_num
        abstract = row.abstract_zh or ""
        abstract_preview = abstract[:ABSTRACT_PREVIEW_MAX_CHARS] if abstract else None

        inventors = extract_names(row.inventor_harmonized)
        assignees = extract_names(row.assignee_harmonized)

        # IPC 分类号
        ipc_codes = []
        if row.ipc:
            for ipc in row.ipc[:5]:
                if isinstance(ipc, dict):
                    code = ipc.get("code", "")
                elif isinstance(ipc, str):
                    code = ipc
                else:
                    continue
                if code:
                    ipc_codes.append(code)

        pub_date = format_date(row.publication_date)
        year = extract_year(row.publication_date)

        country_code = pub_num.split("-")[0] if "-" in pub_num else pub_num[:2]
        patents.append({
            "openalex_id": f"BQ:{pub_num}",
            "doi": None,
            "title": title,
            "publication_year": year,
            "publication_date": pub_date,
            "language": lang,
            "type": "patent",
            "cited_by_count": 0,
            "authors": inventors if inventors else assignees,
            "source_name": assignees if assignees else f"{country_code} Patent",
            "source_issn": None,
            "abstract_preview": abstract_preview,
            "primary_topic_id": ipc_codes[0] if ipc_codes else None,
            "primary_topic_name": "; ".join(ipc_codes) if ipc_codes else None,
            "primary_field_name": "Patent",
            "primary_domain_name": "Patent",
            "countries": country_code,
            "is_oa": False,
            "pdf_url": None,
            "landing_url": f"https://patents.google.com/patent/{pub_num.replace('-', '')}",
        })

    print(f"   Unique patents: {len(patents):,} (deduped)")
    return patents


def run(
    keywords: list[str] = None,
    where_clause: str = None,
    output_dir: Path = Path("data/kb_tobacco"),
    min_year: int = None,
    lang: str = "zh",
    country: str = "CN",
):
    patents = query_bigquery(keywords, where_clause, min_year, lang, country)
    if not patents:
        print("No patents found.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = MetadataStore(output_dir / "metadata.duckdb")
    search = SearchIndex(output_dir / "search.sqlite")
    relations = RelationStore(output_dir / "relations.sqlite")
    metadata.init_schema()
    search.init_schema()
    relations.init_schema()

    print(f"\n>> Writing {len(patents):,} patents to KB...")
    metadata.bulk_insert(patents)
    search.bulk_index(patents)

    # 专利之间通过 family_id 或 IPC 建立关系（简化：同 IPC 前4位视为同族）
    topic_triples = []
    for p in patents:
        if p["primary_topic_id"]:
            # IPC 前 4 位作为 topic（如 A24D = 烟草制品）
            ipc_prefix = p["primary_topic_id"][:4]
            topic_triples.append((p["openalex_id"], ipc_prefix, 1.0))
    if topic_triples:
        relations.bulk_insert_topics(topic_triples)

    search.optimize()

    # 更新 sync_state
    state_path = output_dir / "sync_state.json"
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text())
    state["last_patent_sync"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["patent_keywords"] = keywords
    state["patent_count"] = len(patents)
    state["total_works"] = metadata.count()
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    print(f"\n{'='*50}")
    print(f"[DONE] {len(patents):,} patents added to KB")
    print(f"  Total works in KB: {metadata.count():,}")
    print(f"  FTS indexed: {search.count():,}")

    metadata.close()
    search.close()
    relations.close()


def main():
    parser = argparse.ArgumentParser(description="BigQuery CN patents -> local KB")
    parser.add_argument(
        "--keywords", nargs="+",
        help="Patent keywords (OR logic). e.g. --keywords '爆珠' '烟用香珠' '香味胶囊'"
    )
    parser.add_argument(
        "--where",
        help="Raw SQL WHERE clause for BigQuery"
    )
    parser.add_argument("--output", type=Path, default=Path("data/kb_tobacco"))
    parser.add_argument("--min-year", type=int, default=None)
    parser.add_argument("--lang", default="zh", help="Language: zh or en")
    parser.add_argument("--country", default="CN", help="Country code or * for all")
    args = parser.parse_args()

    if not args.keywords and not args.where:
        parser.error("Must specify --keywords or --where")

    run(args.keywords, args.where, args.output, args.min_year, args.lang, args.country)


if __name__ == "__main__":
    main()
