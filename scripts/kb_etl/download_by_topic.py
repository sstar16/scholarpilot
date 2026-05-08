"""
OpenAlex API 按主题下载 → 直接写入本地知识库

用法:
  # 下载烟草+干细胞相关论文
  python scripts/kb_etl/download_by_topic.py \
    --topics "tobacco,nicotine,cigarette" "stem cell,pluripotent,iPSC" \
    --output data/knowledge_base \
    --min-year 2015

  # 单主题测试（少量）
  python scripts/kb_etl/download_by_topic.py \
    --topics "tobacco nicotine" \
    --output data/knowledge_base \
    --max-works 500

性能:
  OpenAlex API 200条/页，~5 req/s（polite pool）
  10万条 ≈ 3-5 分钟，100万条 ≈ 30-50 分钟
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.knowledge_base.metadata_store import MetadataStore
from backend.app.knowledge_base.search_index import SearchIndex
from backend.app.knowledge_base.relations import RelationStore
from backend.app.knowledge_base.config import ABSTRACT_PREVIEW_MAX_CHARS

# ─── OpenAlex API 配置 ───

OPENALEX_API = "https://api.openalex.org/works"
PER_PAGE = 200
# Polite pool: 加 mailto 到 User-Agent，限速更宽松
USER_AGENT = "ScholarPilot/1.0 (mailto:scholarpilot@example.com)"
REQUEST_DELAY = 0.2  # 200ms between requests ≈ 5 req/s


# ─── 解析函数 ───

def reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    word_positions = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions[pos] = word
    if not word_positions:
        return ""
    max_pos = max(word_positions.keys())
    return " ".join(word_positions.get(i, "") for i in range(max_pos + 1))


def extract_openalex_id(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if uri else ""


def parse_work(raw: dict) -> dict | None:
    """OpenAlex API JSON → KB 扁平 dict"""
    oa_id = extract_openalex_id(raw.get("id", ""))
    if not oa_id:
        return None

    title = raw.get("title") or raw.get("display_name") or ""
    if not title:
        return None

    year = raw.get("publication_year")
    cited = raw.get("cited_by_count", 0) or 0

    abstract_full = reconstruct_abstract(raw.get("abstract_inverted_index"))
    abstract_preview = abstract_full[:ABSTRACT_PREVIEW_MAX_CHARS] if abstract_full else None

    authorships = raw.get("authorships") or []
    authors = "; ".join(
        a.get("raw_author_name") or a.get("author", {}).get("display_name", "")
        for a in authorships[:10]
    )

    primary_loc = raw.get("primary_location") or {}
    source_obj = primary_loc.get("source") or {}

    primary_topic = raw.get("primary_topic") or {}
    topic_id = extract_openalex_id(primary_topic.get("id", ""))

    countries = set()
    for a in authorships:
        for c in (a.get("countries") or []):
            countries.add(c)

    oa_info = raw.get("open_access") or {}
    doi_raw = raw.get("doi") or ""
    doi = doi_raw.replace("https://doi.org/", "") if doi_raw else None

    return {
        "openalex_id": oa_id,
        "doi": doi,
        "title": title,
        "publication_year": year,
        "publication_date": raw.get("publication_date"),
        "language": raw.get("language"),
        "type": raw.get("type"),
        "cited_by_count": cited,
        "authors": authors,
        "source_name": source_obj.get("display_name"),
        "source_issn": source_obj.get("issn_l"),
        "abstract_preview": abstract_preview,
        "primary_topic_id": topic_id or None,
        "primary_topic_name": primary_topic.get("display_name"),
        "primary_field_name": (primary_topic.get("field") or {}).get("display_name"),
        "primary_domain_name": (primary_topic.get("domain") or {}).get("display_name"),
        "countries": ",".join(sorted(countries)) if countries else None,
        "is_oa": oa_info.get("is_oa", False),
        "pdf_url": primary_loc.get("pdf_url"),
        "landing_url": primary_loc.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else None),
    }


def extract_citations(raw: dict) -> list[tuple[str, str]]:
    oa_id = extract_openalex_id(raw.get("id", ""))
    if not oa_id:
        return []
    refs = raw.get("referenced_works") or []
    return [(oa_id, extract_openalex_id(r)) for r in refs if r]


def extract_topics(raw: dict) -> list[tuple[str, str, float]]:
    oa_id = extract_openalex_id(raw.get("id", ""))
    if not oa_id:
        return []
    topics = raw.get("topics") or []
    return [
        (oa_id, extract_openalex_id(t.get("id", "")), t.get("score", 0.0))
        for t in topics if t.get("id")
    ]


# ─── API 分页下载 ───

def fetch_topic(
    search_query: str,
    min_year: int,
    max_works: int | None,
    client: httpx.Client,
) -> list[dict]:
    """从 OpenAlex API cursor 分页获取所有匹配 works 的原始 JSON"""
    params = {
        "search": search_query,
        "per_page": PER_PAGE,
        "cursor": "*",
        "select": "id,doi,title,display_name,publication_year,publication_date,"
                  "language,type,cited_by_count,authorships,primary_location,"
                  "open_access,abstract_inverted_index,referenced_works,"
                  "primary_topic,topics",
    }
    if min_year:
        params["filter"] = f"publication_year:>{min_year - 1}"

    all_raws = []
    page = 0
    total_expected = None

    while True:
        try:
            resp = client.get(OPENALEX_API, params=params, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"  [ERROR] API error: {e}")
            if page == 0:
                return []
            break

        data = resp.json()
        results = data.get("results", [])
        meta = data.get("meta", {})

        if total_expected is None:
            total_expected = meta.get("count", "?")
            print(f"  Found {total_expected:,} works for '{search_query}'")

        if not results:
            break

        all_raws.extend(results)
        page += 1

        if max_works and len(all_raws) >= max_works:
            all_raws = all_raws[:max_works]
            break

        # 进度
        if page % 10 == 0:
            print(f"    ... {len(all_raws):,} / {total_expected:,} fetched")

        # 下一页 cursor
        next_cursor = meta.get("next_cursor")
        if not next_cursor:
            break
        params["cursor"] = next_cursor

        time.sleep(REQUEST_DELAY)

    return all_raws


# ─── 主流程 ───

def run(
    topics: list[str],
    output_dir: Path,
    min_year: int = 2015,
    max_works: int | None = None,
):
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = MetadataStore(output_dir / "metadata.duckdb")
    search = SearchIndex(output_dir / "search.sqlite")
    relations = RelationStore(output_dir / "relations.sqlite")
    metadata.init_schema()
    search.init_schema()
    relations.init_schema()

    t0 = time.time()
    total_works = 0
    total_citations = 0

    client = httpx.Client(headers={"User-Agent": USER_AGENT}, verify=False)

    for topic_query in topics:
        print(f"\n>> Topic: {topic_query}")
        raws = fetch_topic(topic_query, min_year, max_works, client)
        print(f"  Downloaded {len(raws):,} raw works")

        # 批量处理
        work_buf = []
        cite_buf = []
        topic_buf = []
        FLUSH = 5000

        for raw in raws:
            work = parse_work(raw)
            if work is None:
                continue
            work_buf.append(work)
            cite_buf.extend(extract_citations(raw))
            topic_buf.extend(extract_topics(raw))

            if len(work_buf) >= FLUSH:
                metadata.bulk_insert(work_buf)
                search.bulk_index(work_buf)
                relations.bulk_insert_citations(cite_buf)
                relations.bulk_insert_topics(topic_buf)
                total_works += len(work_buf)
                total_citations += len(cite_buf)
                work_buf.clear()
                cite_buf.clear()
                topic_buf.clear()
                print(f"    flushed {total_works:,} works, {total_citations:,} citations")

        # 残留
        if work_buf:
            metadata.bulk_insert(work_buf)
            search.bulk_index(work_buf)
            total_works += len(work_buf)
        if cite_buf:
            relations.bulk_insert_citations(cite_buf)
            total_citations += len(cite_buf)
        if topic_buf:
            relations.bulk_insert_topics(topic_buf)

        print(f"  [OK] Topic done. Running total: {total_works:,} works")

    client.close()

    # 优化 FTS 索引
    print("\n>> Optimizing FTS5 index...")
    search.optimize()

    # 保存同步状态
    from datetime import datetime
    sync_state = {
        "last_processed": datetime.now().isoformat(),
        "topics": topics,
        "min_year": min_year,
        "total_works": total_works,
        "total_citations": total_citations,
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    (output_dir / "sync_state.json").write_text(json.dumps(sync_state, indent=2, ensure_ascii=False))

    # 统计
    elapsed = time.time() - t0
    print(f"\n{'='*50}")
    print(f"[DONE] {total_works:,} works, {total_citations:,} citations in {elapsed:.1f}s")

    for name in ["metadata.duckdb", "search.sqlite", "relations.sqlite"]:
        p = output_dir / name
        if p.exists():
            size_mb = p.stat().st_size / 1e6
            print(f"  {name}: {size_mb:.1f} MB")

    metadata.close()
    search.close()
    relations.close()


def main():
    parser = argparse.ArgumentParser(
        description="从 OpenAlex API 按主题下载论文到本地知识库"
    )
    parser.add_argument(
        "--topics", nargs="+", required=True,
        help="搜索主题（每个参数是一个 OR 查询，多个参数分别下载）"
             " 例: --topics 'tobacco nicotine cigarette' 'stem cell pluripotent'"
    )
    parser.add_argument("--output", type=Path, default=Path("data/knowledge_base"))
    parser.add_argument("--min-year", type=int, default=2015)
    parser.add_argument(
        "--max-works", type=int, default=None,
        help="每个主题最多下载多少条（测试用，默认不限）"
    )
    args = parser.parse_args()

    run(args.topics, args.output, args.min_year, args.max_works)


if __name__ == "__main__":
    main()
