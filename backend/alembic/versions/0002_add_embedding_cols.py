"""add embedding cols to user_profiles

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension exists (safe if already present)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        ALTER TABLE user_profiles
        ADD COLUMN IF NOT EXISTS positive_embedding vector(384),
        ADD COLUMN IF NOT EXISTS negative_embedding vector(384)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
        DROP COLUMN IF EXISTS positive_embedding,
        DROP COLUMN IF EXISTS negative_embedding
    """)
