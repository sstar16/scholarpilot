"""SQLite-based relation graph storage for the knowledge base."""

from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path


_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS citations (
    citing_id TEXT NOT NULL,
    cited_id  TEXT NOT NULL,
    PRIMARY KEY (citing_id, cited_id)
);
CREATE INDEX IF NOT EXISTS idx_cited ON citations(cited_id);

CREATE TABLE IF NOT EXISTS work_topics (
    work_id  TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    score    REAL DEFAULT 1.0,
    PRIMARY KEY (work_id, topic_id)
);
CREATE INDEX IF NOT EXISTS idx_topic ON work_topics(topic_id);

CREATE TABLE IF NOT EXISTS coauthorship (
    author_a   TEXT NOT NULL,
    author_b   TEXT NOT NULL,
    work_count INTEGER DEFAULT 1,
    PRIMARY KEY (author_a, author_b)
);
"""


class RelationStore:
    """SQLite-backed relation graph (citations, topics, coauthorship)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            abs_path = str(self._db_path.absolute() if hasattr(self._db_path, 'absolute') else self._db_path)
            from pathlib import Path as _P
            if _P(abs_path).exists() and _P(abs_path).stat().st_size > 0:
                # 已有文件 → 只读 immutable 模式
                uri = f"file:{abs_path}?mode=ro&immutable=1"
                self._conn = sqlite3.connect(uri, uri=True)
                self._conn.row_factory = sqlite3.Row
            else:
                # 新建 → 读写模式
                self._conn = sqlite3.connect(abs_path)
                self._conn.row_factory = sqlite3.Row
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError:
                    pass
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        # 检测是否只读或已初始化
        try:
            self.conn.execute("SELECT 1 FROM citations LIMIT 1")
            return  # 表已存在
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.executescript(_DDL)
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # 只读模式，跳过 DDL

    # ------------------------------------------------------------------
    # Citations
    # ------------------------------------------------------------------

    def bulk_insert_citations(
        self, pairs: list[tuple[str, str]], batch_size: int = 10000
    ) -> None:
        """Insert (citing_id, cited_id) pairs, ignoring duplicates."""
        sql = "INSERT OR IGNORE INTO citations (citing_id, cited_id) VALUES (?, ?)"
        for start in range(0, len(pairs), batch_size):
            self.conn.executemany(sql, pairs[start : start + batch_size])
        self.conn.commit()

    def citation_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM citations").fetchone()
        return row[0]

    def get_references(self, work_id: str) -> list[str]:
        """Outbound citations: works that *work_id* cites."""
        rows = self.conn.execute(
            "SELECT cited_id FROM citations WHERE citing_id = ?", (work_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def get_cited_by(self, work_id: str) -> list[str]:
        """Inbound citations: works that cite *work_id*."""
        rows = self.conn.execute(
            "SELECT citing_id FROM citations WHERE cited_id = ?", (work_id,)
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Topics
    # ------------------------------------------------------------------

    def bulk_insert_topics(
        self, triples: list[tuple[str, str, float]], batch_size: int = 10000
    ) -> None:
        """Insert (work_id, topic_id, score) triples, replacing on conflict."""
        sql = (
            "INSERT OR REPLACE INTO work_topics (work_id, topic_id, score) "
            "VALUES (?, ?, ?)"
        )
        for start in range(0, len(triples), batch_size):
            self.conn.executemany(sql, triples[start : start + batch_size])
        self.conn.commit()

    def get_same_topic_works(self, work_id: str, limit: int = 50) -> list[str]:
        """Return works that share at least one topic with *work_id*."""
        sql = """
            SELECT DISTINCT wt2.work_id
            FROM work_topics wt1
            JOIN work_topics wt2 ON wt1.topic_id = wt2.topic_id
            WHERE wt1.work_id = ?
              AND wt2.work_id != ?
            LIMIT ?
        """
        rows = self.conn.execute(sql, (work_id, work_id, limit)).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def expand_by_citation(
        self, seed_ids: list[str], hops: int = 1, limit: int = 50
    ) -> list[str]:
        """BFS over citation edges for *hops* steps.

        Returns newly discovered IDs (excluding the original seeds), capped at
        *limit*.
        """
        visited: set[str] = set(seed_ids)
        frontier: deque[str] = deque(seed_ids)
        discovered: list[str] = []

        for _ in range(hops):
            next_frontier: list[str] = []
            while frontier:
                node = frontier.popleft()
                neighbors = self.get_references(node) + self.get_cited_by(node)
                for nb in neighbors:
                    if nb not in visited:
                        visited.add(nb)
                        discovered.append(nb)
                        next_frontier.append(nb)
                        if len(discovered) >= limit:
                            return discovered
            frontier = deque(next_frontier)

        return discovered
