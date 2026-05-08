#!/usr/bin/env python3
"""Backfill user_documents from existing fulltext-available documents.

Spec: docs/spec-pdf-ownership-sync.md §5

为什么需要这个: 0028 加的 GET /file ownership hook (commit 6699453) 之前
所有用户从 web/客户端下载的 PDF 都没有写 user_documents 表 — 导致客户端
silentPdfReconciler 拉到 0 篇 owned, 永远不会自动同步历史 PDF 到本地。

本脚本一次性把 documents.fulltext_(pdf|html)_status='available' 通过
(SearchRound.user_id, document_id, project_id) 三元组关联,
批量补 INSERT 到 user_documents (source='downloaded')。

Usage (backend 容器内, cwd=/app):
    # dry-run preview
    docker compose exec backend python scripts/backfill_user_documents.py
    # 实际写入
    docker compose exec backend python scripts/backfill_user_documents.py --commit

幂等: 多次跑无副作用 — 按 (user_id, doc_id, proj_id, format) 去重,
已存在的不动。

数据安全: 一个事务包所有 INSERT, 中途失败回滚, 不留半截状态。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 让 `python scripts/backfill_user_documents.py` 也能 import `app.*`
# (sys.path[0] 默认是脚本所在目录, 不含 /app, 否则要每次 PYTHONPATH=/app)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models.user_document import UserDocument


async def _fetch_triples(db: AsyncSession, status_col: str):
    """SELECT DISTINCT (user_id, document_id, project_id) for docs with given status='available'."""
    # status_col 是受控字符串 (硬编码列名), 不接受用户输入, 安全
    sql = text(f"""
        SELECT DISTINCT p.user_id, d.id AS document_id, sr.project_id
        FROM documents d
        JOIN round_documents rd ON rd.document_id = d.id
        JOIN search_rounds sr ON sr.id = rd.round_id
        JOIN projects p ON p.id = sr.project_id
        WHERE d.{status_col} = 'available'
    """)
    rows = (await db.execute(sql)).fetchall()
    return [(r.user_id, r.document_id, r.project_id) for r in rows]


async def _existing_keys(db: AsyncSession):
    """读现有 user_documents 的去重键集合, 用于 client-side 去重避免 ON CONFLICT 噪声日志。"""
    rows = (
        await db.execute(text(
            "SELECT user_id, document_id, project_id, format FROM user_documents"
        ))
    ).fetchall()
    return {(r.user_id, r.document_id, r.project_id, r.format) for r in rows}


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill user_documents from existing fulltext-available documents",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="实际写入 (默认 dry-run, 只打印预览)",
    )
    args = parser.parse_args()

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with session_factory() as db:
            # 拉两个 format 的三元组
            pdf_triples = await _fetch_triples(db, "fulltext_pdf_status")
            html_triples = await _fetch_triples(db, "fulltext_html_status")

            print("=== Preview ===")
            print(f"  PDF  candidate triples : {len(pdf_triples)}")
            print(f"  HTML candidate triples : {len(html_triples)}")

            if not pdf_triples and not html_triples:
                print(
                    "\n[empty] no fulltext-available documents found, "
                    "nothing to backfill"
                )
                return 0

            # 客户端去重 (避免重跑时 ORM 抛 IntegrityError)
            existing = await _existing_keys(db)
            print(f"  user_documents existing: {len(existing)}")

            new_pdf = [t for t in pdf_triples if (*t, "pdf") not in existing]
            new_html = [t for t in html_triples if (*t, "html") not in existing]

            print(f"\n  to insert (PDF) : {len(new_pdf)}")
            print(f"  to insert (HTML): {len(new_html)}")

            if not new_pdf and not new_html:
                print("\n[no-op] all candidates already in user_documents")
                return 0

            if not args.commit:
                print("\n[dry-run] add --commit to actually insert")
                return 0

            # ORM batch insert: uuid 走 model default=uuid.uuid4,
            # owned_at/last_seen_at 走 default=lambda: datetime.now(tz)
            print("\n=== Inserting ===")
            before = (
                await db.execute(text("SELECT COUNT(*) FROM user_documents"))
            ).scalar_one()
            print(f"  user_documents before : {before}")

            for user_id, doc_id, proj_id in new_pdf:
                db.add(
                    UserDocument(
                        user_id=user_id,
                        document_id=doc_id,
                        project_id=proj_id,
                        source="downloaded",
                        format="pdf",
                    )
                )
            for user_id, doc_id, proj_id in new_html:
                db.add(
                    UserDocument(
                        user_id=user_id,
                        document_id=doc_id,
                        project_id=proj_id,
                        source="downloaded",
                        format="html",
                    )
                )
            await db.commit()

            after = (
                await db.execute(text("SELECT COUNT(*) FROM user_documents"))
            ).scalar_one()
            print(f"  user_documents after  : {after}")
            print(f"  inserted (PDF + HTML) : +{after - before}")

        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
