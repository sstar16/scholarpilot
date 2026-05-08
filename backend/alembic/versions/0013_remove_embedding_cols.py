"""remove embedding columns (彻底删除 embedding 功能)

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-14

Phase 2 的 embedding 功能未进入生产（sentence-transformers / numpy 从未装进
worker 镜像，反馈后 Celery 任务一直失败）。MemoryAgent 已经提供了画像学习
的主力（LLM-driven preferred_topics / excluded_topics），embedding 作为
"第二层语义排序"的计划被永久删除。

删除：
- user_profiles.positive_embedding (vector 384)
- user_profiles.negative_embedding (vector 384)
- documents.embedding (text, pgvector 不可用时的占位 fallback)

保留 vector extension，防止其他数据库对象被破坏。幂等 DROP IF EXISTS。
"""
from alembic import op


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
        DROP COLUMN IF EXISTS positive_embedding,
        DROP COLUMN IF EXISTS negative_embedding
    """)
    op.execute("""
        ALTER TABLE documents
        DROP COLUMN IF EXISTS embedding
    """)


def downgrade() -> None:
    # 不提供回滚：embedding 已永久删除
    pass
