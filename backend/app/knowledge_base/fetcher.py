"""
LocalKBFetcher — 本地知识库检索器

实现 AbstractFetcher 接口，接入现有检索管线。
BM25 FTS5 全文匹配 -> 元数据补全 -> 返回标准 doc dict。

2026-04-25 调整：彻底移除引用扩展步骤。
扩展逻辑不经过关键词匹配，会让结果混进与主题无关的"引用链"文献。
保证 local_kb 100% 按关键词召回，精度优先。
"""
import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple

try:
    from app.knowledge_base.config import KB_DATA_DIR
    from app.knowledge_base.metadata_store import MetadataStore
    from app.knowledge_base.search_index import SearchIndex
    from app.knowledge_base.relations import RelationStore
    from app.services.fetchers.base import AbstractFetcher
except ImportError:
    from backend.app.knowledge_base.config import KB_DATA_DIR
    from backend.app.knowledge_base.metadata_store import MetadataStore
    from backend.app.knowledge_base.search_index import SearchIndex
    from backend.app.knowledge_base.relations import RelationStore
    from backend.app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

import re as _re

# FTS5 需要特殊处理的字符（纯词模式下剥离；布尔桶模式保留）
_FTS5_RESERVED = set('()"*-:')

# 检测布尔桶结构：含括号分组，或显式 AND/OR/NOT/NEAR 操作符
_BOOLEAN_BUCKET_RE = _re.compile(r'[()]|\b(AND|OR|NOT|NEAR)\b')


def _oa_id_to_external_url(oa_id: str, doi: Optional[str] = None) -> str:
    """根据 openalex_id 前缀或 doi 生成可点击的外部 URL。

    - 有 doi → doi.org
    - W 开头 → openalex.org
    - CN: 开头 → google patents（去掉 - 后缀字母仍兼容）
    - LENS: 开头 → lens.org
    - 兜底 → openalex.org/{oa_id}（即使 404 也保证非空，让前端按钮可点）
    """
    if doi:
        return f"https://doi.org/{doi}"
    if not oa_id:
        return ""
    if oa_id.startswith("W"):
        return f"https://openalex.org/{oa_id}"
    if oa_id.startswith("CN:"):
        raw = oa_id[3:]
        cleaned = raw.replace("-", "")
        return f"https://patents.google.com/patent/{cleaned}"
    if oa_id.startswith("LENS:"):
        return f"https://www.lens.org/lens/patent/{oa_id[5:]}"
    return f"https://openalex.org/{oa_id}"


def _to_or_query(query: str) -> str:
    """
    把 LLM 查询转成 FTS5 合法语法。

    - **布尔桶格式**（含括号或 AND/OR/NOT/NEAR 操作符）→ 原样传给 FTS5。
      SQLite FTS5 原生支持 `(A OR B) AND (C OR D)` / `"phrase"` / `col:term`
      这些语法，之前无脑拆词会丢掉桶 AND 桶的精度约束。
    - **纯词模式** → 用 OR 连接所有词（单词查询保持原样），
      BM25 按匹配词数自动排序（匹配更多词 = 更高分）。

    例：
      - `(锂电池 OR LFP) AND (正极 OR 电极)` → 原样
      - `lithium cathode stability` → `lithium OR cathode OR stability`
    """
    if not query or not query.strip():
        return query

    # 布尔桶：FTS5 原生支持 (), AND/OR/NOT/NEAR，原样传
    if _BOOLEAN_BUCKET_RE.search(query):
        # 只清理明确会让 FTS5 parser 炸的孤立 `*`（非前缀场景）
        # `-` 不是 FTS5 语法（要用 NOT），但用户可能写 `"high-entropy"` 这种，
        # 保留引号内的 `-` 由 FTS5 自己处理 —— 此处不做替换，交 FTS5 决定。
        return query.strip()

    # 纯词模式：OR 连接
    cleaned = "".join(c if c not in _FTS5_RESERVED else " " for c in query)
    tokens = [
        t.strip() for t in cleaned.split()
        if len(t.strip()) >= 2 and t.strip().upper() not in ("AND", "OR", "NOT", "NEAR")
    ]
    if not tokens:
        return query
    if len(tokens) == 1:
        return tokens[0]
    return " OR ".join(tokens)


class LocalKBFetcher(AbstractFetcher):
    """本地知识库 fetcher，BM25 搜索 + 引用扩展"""

    DEFAULT_TIMEOUT = 2.0  # 本地查询极快

    def __init__(self, kb_data_dir: Path | None = None):
        self._kb_dir = Path(kb_data_dir) if kb_data_dir else KB_DATA_DIR
        self._metadata: MetadataStore | None = None
        self._search: SearchIndex | None = None
        self._relations: RelationStore | None = None

    @property
    def source_id(self) -> str:
        return "local_kb"

    def is_available(self) -> bool:
        """检查 KB 数据文件是否存在（只需 search.sqlite，metadata 可选）"""
        return (self._kb_dir / "search.sqlite").exists()

    def _ensure_loaded(self):
        if self._search is None:
            self._search = SearchIndex(self._kb_dir / "search.sqlite")
            self._search.init_schema()
        if self._metadata is None:
            meta_path = self._kb_dir / "metadata.duckdb"
            if meta_path.exists():
                self._metadata = MetadataStore(meta_path)
                self._metadata.init_schema()
        if self._relations is None and (self._kb_dir / "relations.sqlite").exists():
            self._relations = RelationStore(self._kb_dir / "relations.sqlite")
            self._relations.init_schema()

    def close(self):
        if self._metadata:
            self._metadata.close()
            self._metadata = None
        if self._search:
            self._search.close()
            self._search = None
        if self._relations:
            self._relations.close()
            self._relations = None

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        self._ensure_loaded()

        # 将多词查询转为 OR 语义，让 BM25 按匹配词数排序（FTS5 默认是 AND）
        or_query = _to_or_query(query)
        fts_limit = max_results * 3

        # ── Smart Retrieve（feature flag）──
        # LLM 生成 N 路 diverse query (中英互译/技术细节/上位词) → 并行 BM25 → RRF 融合。
        # 根治 BM25 单 query 召回不足（jieba 漏召英文同义词、上位概念等）。
        # 任何异常自动降级到下方单 query 路径，不让上游炸掉。
        fts_hits = []
        try:
            from app.config import settings as _s
            if _s.enable_smart_retrieve:
                from app.services.smart_retriever import smart_retrieve
                from app.services.core.llm_config_store import get_llm_manager

                _llm = await get_llm_manager()

                class _OrQueryAdapter:
                    # 包装 SearchIndex —— LLM 生成的 diverse query 是纯词，
                    # FTS5 默认 AND，不转 OR 会因 1 个词不命中整条丢。
                    __slots__ = ("_idx",)
                    def __init__(_self, idx):
                        _self._idx = idx
                    def search(_self, q, limit, year_from=None, year_to=None):
                        return _self._idx.search(
                            _to_or_query(q), limit, year_from, year_to,
                        )

                env = await smart_retrieve(
                    query, _OrQueryAdapter(self._search), _llm,
                    n_queries=_s.smart_retrieve_n_queries,
                    per_query_limit=fts_limit,
                    final_top_k=fts_limit,
                    year_from=year_from, year_to=year_to,
                )
                fts_hits = env.get("docs") or []
                logger.info(
                    "[LocalKB+Smart] q=%r diverse=%d hits=%s fused=%d (%s)",
                    query[:60],
                    len(env.get("queries_used", [])),
                    env.get("per_query_counts"),
                    len(fts_hits),
                    env.get("fallback_reason") or "ok",
                )
        except Exception as _e:
            logger.warning("[LocalKB] smart_retrieve failed, fallback to single: %s", _e)
            fts_hits = []

        # Step 1: BM25 单 query 粗筛（Smart 关闭 / Smart 失败 / Smart 零结果时走这里）
        if not fts_hits:
            fts_hits = self._search.search(
                or_query, limit=fts_limit, year_from=year_from, year_to=year_to
            )
        if not fts_hits:
            # 最后尝试：只取前 3 个词用 AND（核心语义）
            tokens = [t for t in query.split() if len(t) >= 2][:3]
            if tokens:
                fts_hits = self._search.search(
                    " ".join(tokens), limit=fts_limit,
                    year_from=year_from, year_to=year_to,
                )
            if not fts_hits:
                return []

        hit_ids = [h["openalex_id"] for h in fts_hits]

        # Step 2: 拿完整元数据（metadata 可选；无 metadata.duckdb 时走 FTS5 fallback）
        meta_map = {}
        if self._metadata:
            try:
                metadata_rows = self._metadata.get_by_ids(hit_ids)
                meta_map = {r["openalex_id"]: r for r in metadata_rows}
            except Exception as e:
                logger.warning("[LocalKB] metadata query failed: %s", e)

        # Step 3: 按 BM25 顺序组装结果
        results = []
        if meta_map:
            for oid in hit_ids:
                if oid in meta_map:
                    results.append(self._to_doc_dict(meta_map[oid]))
        else:
            fts_content = self._search.get_content_by_ids(hit_ids[:max_results])
            fts_map = {r["openalex_id"]: r for r in fts_content}
            for oid in hit_ids:
                if oid in fts_map:
                    results.append(self._fts_to_doc_dict(fts_map[oid]))

        # 语言过滤
        if language:
            lang_code = "zh" if language == "chinese" else "en"
            results = [r for r in results if r.get("_kb_language") in (lang_code, None)]

        logger.info(f"LocalKB: query='{query[:50]}' fts={len(fts_hits)} final={min(len(results), max_results)}")
        return results[:max_results]

    def _fts_to_doc_dict(self, row: dict) -> dict:
        """将 FTS5 行转为标准输出格式（无 metadata.duckdb 时的 fallback）"""
        oa_id = row.get("openalex_id", "")
        doi = row.get("doi") or None
        return {
            "source": "local_kb",
            "external_id": oa_id,
            "doc_type": "patent" if oa_id.startswith(("CN:", "LENS:")) else "paper",
            "title": row.get("title") or "",
            "authors": row.get("authors") or "",
            "abstract": row.get("abstract_preview") or "",
            "publication_date": str(row.get("publication_year") or ""),
            "url": _oa_id_to_external_url(oa_id, doi),
            "doi": doi,
            "journal": row.get("source_name") or "",
            "citation_count": 0,
            "pdf_url": "",
            "countries": [],
        }

    def _to_doc_dict(self, row: dict) -> dict:
        """将 DuckDB 行转为 AbstractFetcher 标准输出格式"""
        oa_id = row["openalex_id"]
        doi = row.get("doi")
        # 多源字段（A 方案 Phase 1）：优先读新列，fallback 解析前缀
        src = row.get("source")
        if not src:
            src = (
                "openalex" if oa_id.startswith("W")
                else "cnipr" if oa_id.startswith("CN:")
                else "lens" if oa_id.startswith("LENS:")
                else "user" if oa_id.startswith("user:")
                else "local_kb"
            )
        # 文档类型：用 works.type 映射
        raw_type = (row.get("type") or "").lower()
        doc_type = (
            "patent" if raw_type == "patent"
            else "preprint" if raw_type == "preprint"
            else "thesis" if raw_type == "dissertation"
            else "paper"
        )
        return {
            "source": src,
            "external_id": row.get("external_id") or oa_id,
            "doc_type": doc_type,
            "title": row.get("title") or "",
            "authors": row.get("authors") or "",
            "abstract": row.get("abstract_preview") or "",
            "publication_date": str(row.get("publication_date") or ""),
            "url": row.get("landing_url") or _oa_id_to_external_url(oa_id, doi),
            "doi": doi,
            "journal": row.get("source_name") or "",
            "citation_count": row.get("cited_by_count") or 0,
            "pdf_url": row.get("pdf_url") or "",
            "countries": (row.get("countries") or "").split(",") if row.get("countries") else [],
            "_kb_language": row.get("language"),
            "_kb_topic": row.get("primary_topic_name"),
        }
