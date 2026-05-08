"""
SQLite FTS5 全文搜索索引 — BM25 排序 + jieba 中文分词
"""
import re
import sqlite3
from pathlib import Path

import jieba

# CJK 字符检测正则
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# BM25 权重：title=10, abstract=5, authors=2, source=1
# FTS5 bm25() 参数顺序对应 FTS5 content 列顺序（不含 UNINDEXED 列）
_BM25_WEIGHTS = "bm25(fts_works, 0, 10.0, 5.0, 2.0, 1.0, 0)"


def _segment_if_cjk(text: str | None) -> str:
    """若文本含 CJK 字符则用 jieba 分词，否则原样返回。"""
    if not text:
        return text or ""
    if _CJK_RE.search(text):
        return " ".join(jieba.cut_for_search(text))
    return text


class SearchIndex:
    """SQLite FTS5 搜索索引，支持 BM25 排序和年份范围过滤。"""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            abs_path = str(self._db_path.absolute() if hasattr(self._db_path, 'absolute') else self._db_path)
            # 文件已存在 → 只读 immutable 模式（兼容 Windows Docker bind mount）
            from pathlib import Path as _P
            if _P(abs_path).exists() and _P(abs_path).stat().st_size > 0:
                uri = f"file:{abs_path}?mode=ro&immutable=1"
                self._conn = sqlite3.connect(uri, uri=True)
                self._conn.row_factory = sqlite3.Row
            else:
                # 新建场景：正常 WAL 模式
                self._conn = sqlite3.connect(abs_path)
                self._conn.row_factory = sqlite3.Row
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.execute("PRAGMA synchronous=NORMAL")
                except sqlite3.OperationalError:
                    pass
        return self._conn

    def init_schema(self) -> None:
        """创建 FTS5 虚拟表、works_meta 表及索引（只读模式下跳过）。"""
        conn = self._get_conn()
        # 已有数据库：表必定存在，跳过 DDL
        try:
            conn.execute("SELECT 1 FROM fts_works LIMIT 1")
            return
        except sqlite3.OperationalError:
            pass
        try:
            conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_works USING fts5(
                openalex_id UNINDEXED,
                title,
                abstract_preview,
                authors,
                source_name,
                publication_year UNINDEXED,
                tokenize='unicode61'
            );

            CREATE TABLE IF NOT EXISTS works_meta (
                openalex_id TEXT PRIMARY KEY,
                publication_year INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_works_meta_year
                ON works_meta(publication_year);
            """)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 只读模式下跳过 DDL

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def bulk_index(self, works: list[dict], batch_size: int = 5000) -> None:
        """批量索引文献。按 ID 删旧再插新（幂等，支持增量调用）。"""
        conn = self._get_conn()

        for i in range(0, len(works), batch_size):
            batch = works[i:i + batch_size]
            fts_rows = []
            meta_rows = []
            oids = []

            for w in batch:
                oid = w.get("openalex_id") or ""
                title = _segment_if_cjk(w.get("title") or "")
                abstract = _segment_if_cjk(w.get("abstract_preview") or "")
                authors = w.get("authors") or ""
                source = w.get("source_name") or ""
                year = w.get("publication_year")

                oids.append((oid,))
                fts_rows.append((oid, title, abstract, authors, source, year))
                meta_rows.append((oid, year))

            # 先删旧记录（幂等）
            conn.executemany("DELETE FROM fts_works WHERE openalex_id = ?", oids)
            conn.executemany("DELETE FROM works_meta WHERE openalex_id = ?", oids)
            # 插入新记录
            conn.executemany(
                "INSERT INTO fts_works"
                " (openalex_id, title, abstract_preview, authors, source_name, publication_year)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                fts_rows,
            )
            conn.executemany(
                "INSERT OR REPLACE INTO works_meta (openalex_id, publication_year) VALUES (?, ?)",
                meta_rows,
            )
            conn.commit()

    def count(self) -> int:
        """返回已索引文献数量。"""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM fts_works").fetchone()
        return row[0] if row else 0

    def search(
        self,
        query: str,
        limit: int = 200,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[dict]:
        """
        FTS5 全文搜索，返回 [{openalex_id, bm25_score, publication_year}, ...]。
        BM25 值为负数，越小（绝对值越大）表示越相关。
        """
        conn = self._get_conn()

        # 对查询词也做 CJK 分词
        segmented_query = _segment_if_cjk(query)

        try:
            if year_from is not None or year_to is not None:
                # 年份过滤：JOIN works_meta
                conditions = []
                params: list = [segmented_query]
                if year_from is not None:
                    conditions.append("m.publication_year >= ?")
                    params.append(year_from)
                if year_to is not None:
                    conditions.append("m.publication_year <= ?")
                    params.append(year_to)
                where_clause = " AND ".join(conditions)
                sql = f"""
                    SELECT f.openalex_id,
                           {_BM25_WEIGHTS} AS bm25_score,
                           f.publication_year
                    FROM fts_works f
                    JOIN works_meta m ON f.openalex_id = m.openalex_id
                    WHERE fts_works MATCH ?
                      AND {where_clause}
                    ORDER BY bm25_score
                    LIMIT ?
                """
                params.append(limit)
                rows = conn.execute(sql, params).fetchall()
            else:
                sql = f"""
                    SELECT openalex_id,
                           {_BM25_WEIGHTS} AS bm25_score,
                           publication_year
                    FROM fts_works
                    WHERE fts_works MATCH ?
                    ORDER BY bm25_score
                    LIMIT ?
                """
                rows = conn.execute(sql, (segmented_query, limit)).fetchall()

            return [
                {
                    "openalex_id": row["openalex_id"],
                    "bm25_score": row["bm25_score"],
                    "publication_year": row["publication_year"],
                }
                for row in rows
            ]

        except sqlite3.OperationalError:
            # FTS5 语法错误（如特殊字符）时返回空结果
            return []

    def get_content_by_ids(self, ids: list[str]) -> list[dict]:
        """从 FTS5 表获取完整内容（无 metadata.duckdb 时的 fallback）"""
        if not ids:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT openalex_id, title, abstract_preview, authors, source_name, publication_year "
            f"FROM fts_works WHERE openalex_id IN ({placeholders})",
            ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def optimize(self) -> None:
        """运行 FTS5 optimize，ETL 完成后调用以压缩索引。"""
        conn = self._get_conn()
        conn.execute("INSERT INTO fts_works(fts_works) VALUES('optimize')")
        conn.commit()
