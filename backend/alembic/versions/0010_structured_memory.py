"""add structured_memory column to user_profiles

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-10
"""
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS structured_memory JSONB DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS structured_memory")
