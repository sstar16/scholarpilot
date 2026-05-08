"""add domains, search_config, max_rounds to projects

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS domains jsonb DEFAULT '[]'::jsonb,
        ADD COLUMN IF NOT EXISTS search_config jsonb,
        ADD COLUMN IF NOT EXISTS max_rounds integer DEFAULT 5
    """)
    # 迁移现有 domain 到 domains 数组
    op.execute("""
        UPDATE projects
        SET domains = jsonb_build_array(domain)
        WHERE domain IS NOT NULL AND domain != '' AND (domains IS NULL OR domains = '[]'::jsonb)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE projects
        DROP COLUMN IF EXISTS domains,
        DROP COLUMN IF EXISTS search_config,
        DROP COLUMN IF EXISTS max_rounds
    """)
