"""add source_stats to search_rounds

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE search_rounds
        ADD COLUMN IF NOT EXISTS source_stats jsonb
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE search_rounds
        DROP COLUMN IF EXISTS source_stats
    """)
