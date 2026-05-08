"""add scoring agent columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # round_documents: scoring agent fields
    op.execute("""
        ALTER TABLE round_documents
        ADD COLUMN IF NOT EXISTS agent_score float,
        ADD COLUMN IF NOT EXISTS agent_rationale text,
        ADD COLUMN IF NOT EXISTS one_line_summary text,
        ADD COLUMN IF NOT EXISTS below_cutoff boolean DEFAULT false
    """)

    # documents: canonical one-line summary
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS one_line_summary text
    """)

    # user_profiles: memory agent fields
    op.execute("""
        ALTER TABLE user_profiles
        ADD COLUMN IF NOT EXISTS memory_text text,
        ADD COLUMN IF NOT EXISTS memory_version integer DEFAULT 0
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE round_documents
        DROP COLUMN IF EXISTS agent_score,
        DROP COLUMN IF EXISTS agent_rationale,
        DROP COLUMN IF EXISTS one_line_summary,
        DROP COLUMN IF EXISTS below_cutoff
    """)
    op.execute("""
        ALTER TABLE documents
        DROP COLUMN IF EXISTS one_line_summary
    """)
    op.execute("""
        ALTER TABLE user_profiles
        DROP COLUMN IF EXISTS memory_text,
        DROP COLUMN IF EXISTS memory_version
    """)
