"""add expires_at to search_rounds

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_rounds",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_search_rounds_expires_at",
        "search_rounds",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_search_rounds_expires_at", table_name="search_rounds")
    op.drop_column("search_rounds", "expires_at")
