"""
DuckDB-based metadata storage for local knowledge base.
Stores OpenAlex work records with filtering and stats capabilities.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS works (
    -- Identity (openalex_id 作为统一主键，可保存 W*/CN:*/LENS:*/user:* 等前缀 ID)
    openalex_id          VARCHAR PRIMARY KEY,
    -- 多源元数据 (A 方案 Phase 1, 2026-04-12)
    source               VARCHAR,           -- openalex|cnipr|lens|arxiv|user|...
    external_id          VARCHAR,           -- 源的原始 ID (去除前缀)
    -- 通用字段
    doi                  VARCHAR,
    title                VARCHAR NOT NULL,
    publication_year     SMALLINT,
    publication_date     DATE,
    language             VARCHAR(10),
    type                 VARCHAR(30),       -- article|patent|review|preprint|...
    cited_by_count       INTEGER DEFAULT 0,
    authors              VARCHAR,           -- Papers: authors; Patents: inventors
    source_name          VARCHAR,           -- Papers: journal; Patents: patent_office display
    source_issn          VARCHAR,
    abstract_preview     VARCHAR,
    primary_topic_id     VARCHAR,
    primary_topic_name   VARCHAR,
    primary_field_name   VARCHAR,
    primary_domain_name  VARCHAR,
    countries            VARCHAR,
    is_oa                BOOLEAN,
    pdf_url              VARCHAR,
    landing_url          VARCHAR,
    -- Patent-specific (NULL for papers)
    patent_office        VARCHAR,           -- CN|US|EP|WO|LENS
    patent_assignees     VARCHAR,           -- 申请人/专利权人
    patent_ipc_codes     VARCHAR            -- IPC 分类号
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_works_year        ON works (publication_year);",
    "CREATE INDEX IF NOT EXISTS idx_works_doi         ON works (doi);",
    "CREATE INDEX IF NOT EXISTS idx_works_topic       ON works (primary_topic_id);",
    "CREATE INDEX IF NOT EXISTS idx_works_language    ON works (language);",
    "CREATE INDEX IF NOT EXISTS idx_works_source      ON works (source);",
    "CREATE INDEX IF NOT EXISTS idx_works_external_id ON works (external_id);",
    "CREATE INDEX IF NOT EXISTS idx_works_doc_type    ON works (type);",
]

_COLUMNS = [
    "openalex_id", "source", "external_id", "doi", "title",
    "publication_year", "publication_date", "language", "type",
    "cited_by_count", "authors", "source_name", "source_issn",
    "abstract_preview", "primary_topic_id", "primary_topic_name",
    "primary_field_name", "primary_domain_name", "countries", "is_oa",
    "pdf_url", "landing_url",
    "patent_office", "patent_assignees", "patent_ipc_codes",
]


class MetadataStore:
    """DuckDB-backed store for OpenAlex work metadata."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            # 已存在且非空 → 只读模式（兼容 :ro 挂载 & Windows bind mount）
            if self._db_path.exists() and self._db_path.stat().st_size > 0:
                try:
                    self._conn = duckdb.connect(str(self._db_path), read_only=True)
                except Exception:
                    self._conn = duckdb.connect(str(self._db_path))
            else:
                self._conn = duckdb.connect(str(self._db_path))
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create the works table and indexes if they do not exist (skip in read-only)."""
        try:
            self.conn.execute(_CREATE_TABLE_SQL)
            for sql in _CREATE_INDEXES_SQL:
                self.conn.execute(sql)
        except (duckdb.IOException, duckdb.CatalogException, Exception):
            # 只读模式下表必然已存在，跳过 DDL
            pass

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def bulk_insert(self, works: list[dict], batch_size: int = 10_000) -> int:
        """
        Insert or replace work records.

        Returns the total number of rows inserted/replaced.
        """
        if not works:
            return 0

        placeholders = ", ".join(["?"] * len(_COLUMNS))
        sql = (
            f"INSERT OR REPLACE INTO works ({', '.join(_COLUMNS)}) "
            f"VALUES ({placeholders})"
        )

        total = 0
        for start in range(0, len(works), batch_size):
            batch = works[start : start + batch_size]
            rows = [
                tuple(w.get(col) for col in _COLUMNS)
                for w in batch
            ]
            self.conn.executemany(sql, rows)
            total += len(batch)

        return total

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of rows in the works table."""
        result = self.conn.execute("SELECT COUNT(*) FROM works").fetchone()
        return result[0] if result else 0

    def _fetch_as_dicts(self, sql: str, params: list | None = None) -> list[dict]:
        """Execute SQL and return rows as list of dicts (numpy/pandas-free)."""
        cursor = self.conn.execute(sql, params or [])
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def get_by_ids(self, ids: list[str]) -> list[dict]:
        """Return rows matching the given openalex_ids as a list of dicts."""
        if not ids:
            return []
        placeholders = ", ".join(["?"] * len(ids))
        sql = f"SELECT * FROM works WHERE openalex_id IN ({placeholders})"
        return self._fetch_as_dicts(sql, ids)

    def query(
        self,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        topic_id: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Filtered query over the works table.

        Results are sorted by cited_by_count DESC.
        """
        conditions: list[str] = []
        params: list = []

        if year_from is not None:
            conditions.append("publication_year >= ?")
            params.append(year_from)
        if year_to is not None:
            conditions.append("publication_year <= ?")
            params.append(year_to)
        if topic_id is not None:
            conditions.append("primary_topic_id = ?")
            params.append(topic_id)
        if language is not None:
            conditions.append("language = ?")
            params.append(language)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = (
            f"SELECT * FROM works {where_clause} "
            f"ORDER BY cited_by_count DESC "
            f"LIMIT ?"
        )
        params.append(limit)

        return self._fetch_as_dicts(sql, params)

    def stats(self) -> dict:
        """
        Return summary statistics:
          - total_works: int
          - by_year:     list of {publication_year, count}
          - by_language: list of {language, count}
        """
        total = self.count()

        by_year = self._fetch_as_dicts(
            "SELECT publication_year, COUNT(*) AS count "
            "FROM works "
            "GROUP BY publication_year "
            "ORDER BY publication_year"
        )

        by_language = self._fetch_as_dicts(
            "SELECT language, COUNT(*) AS count "
            "FROM works "
            "GROUP BY language "
            "ORDER BY count DESC"
        )

        return {
            "total_works": total,
            "by_year": by_year,
            "by_language": by_language,
        }
