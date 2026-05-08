"""add countries column to documents

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-08
"""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS countries VARCHAR(5)[] DEFAULT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS countries")
