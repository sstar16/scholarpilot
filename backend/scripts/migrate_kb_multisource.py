"""
KB 多源统一 schema 迁移 (Phase 1, 非破坏性)

目的：为 works 表添加 source/external_id/patent_* 列，从 openalex_id 前缀解析填充。
保持 openalex_id 作为 PK（向后兼容），仅新增元数据列。

运行：
    python backend/scripts/migrate_kb_multisource.py [kb_data_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb


def migrate(kb_dir: Path) -> None:
    db_path = kb_dir / "metadata.duckdb"
    if not db_path.exists():
        print(f"ERROR: {db_path} not found")
        sys.exit(1)

    conn = duckdb.connect(str(db_path))

    # 检查已有列
    cols = {r[0] for r in conn.execute("DESCRIBE works").fetchall()}
    print(f"Existing columns: {sorted(cols)}")

    added = []

    def add_col(name: str, sql_type: str):
        if name not in cols:
            conn.execute(f"ALTER TABLE works ADD COLUMN {name} {sql_type}")
            added.append(name)

    add_col("source", "VARCHAR")
    add_col("external_id", "VARCHAR")
    add_col("patent_office", "VARCHAR")
    add_col("patent_assignees", "VARCHAR")
    add_col("patent_ipc_codes", "VARCHAR")

    if added:
        print(f"Added columns: {added}")
    else:
        print("All columns already present")

    # 填充 source / external_id from openalex_id prefix
    print("\nPopulating source + external_id from openalex_id prefix...")
    conn.execute("""
        UPDATE works SET
            source = CASE
                WHEN openalex_id LIKE 'W%' THEN 'openalex'
                WHEN openalex_id LIKE 'CN:%' THEN 'cnipr'
                WHEN openalex_id LIKE 'LENS:%' THEN 'lens'
                WHEN openalex_id LIKE 'user:%' THEN 'user'
                ELSE 'unknown'
            END,
            external_id = CASE
                WHEN openalex_id LIKE 'CN:%' THEN SUBSTR(openalex_id, 4)
                WHEN openalex_id LIKE 'LENS:%' THEN SUBSTR(openalex_id, 6)
                WHEN openalex_id LIKE 'user:%' THEN SUBSTR(openalex_id, 6)
                ELSE openalex_id
            END
        WHERE source IS NULL OR external_id IS NULL
    """)

    # patent_office for CN patents
    print("Populating patent_office for patents...")
    conn.execute("""
        UPDATE works SET patent_office = 'CN'
        WHERE type = 'patent' AND openalex_id LIKE 'CN:CN-%' AND patent_office IS NULL
    """)
    conn.execute("""
        UPDATE works SET patent_office = 'LENS'
        WHERE type = 'patent' AND openalex_id LIKE 'LENS:%' AND patent_office IS NULL
    """)

    # 索引
    print("\nCreating indexes...")
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_works_source ON works(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_works_external_id ON works(external_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_works_doc_type ON works(type)")
    except Exception as e:
        print(f"Index warn: {e}")

    # 统计
    print("\n=== Post-migration stats ===")
    rows = conn.execute("""
        SELECT source, COUNT(*) AS c
        FROM works GROUP BY source ORDER BY c DESC
    """).fetchall()
    for src, cnt in rows:
        print(f"  source={src}: {cnt}")

    print()
    rows = conn.execute("""
        SELECT type, COUNT(*) AS c
        FROM works GROUP BY type ORDER BY c DESC LIMIT 10
    """).fetchall()
    for t, cnt in rows:
        print(f"  type={t}: {cnt}")

    conn.close()
    print("\n[OK] Migration complete")


if __name__ == "__main__":
    default_dir = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"
    kb_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir
    print(f"KB dir: {kb_dir}")
    migrate(kb_dir)
