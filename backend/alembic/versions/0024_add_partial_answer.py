"""add search_rounds.partial_answer / partial_completed_at fields (Answer Now)

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-26

新增 Answer Now 快通道支持：
- partial_answer JSONB：用户中途请求合成的 best-effort 答案
- partial_completed_at：partial 答案落库时间

partial_complete 是 status 字段的新合法终态值（status 列本身已是 String(30)
变长，不需要枚举迁移）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_rounds",
        sa.Column("partial_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "search_rounds",
        sa.Column("partial_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("search_rounds", "partial_completed_at")
    op.drop_column("search_rounds", "partial_answer")
