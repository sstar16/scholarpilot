"""add monitoring_pushes table and monitor_jobs push columns

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-10
"""
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New table for push entries
    op.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_pushes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            novelty_score REAL DEFAULT 0.0,
            push_summary TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_monpush_project ON monitoring_pushes(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_monpush_status ON monitoring_pushes(status)")

    # Add columns to monitor_jobs
    op.execute("ALTER TABLE monitor_jobs ADD COLUMN IF NOT EXISTS novelty_threshold REAL DEFAULT 0.6")
    op.execute("ALTER TABLE monitor_jobs ADD COLUMN IF NOT EXISTS push_config JSONB DEFAULT '{}'")
    op.execute("ALTER TABLE monitor_jobs ADD COLUMN IF NOT EXISTS pending_push_count INTEGER DEFAULT 0")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS monitoring_pushes")
    op.execute("ALTER TABLE monitor_jobs DROP COLUMN IF EXISTS novelty_threshold")
    op.execute("ALTER TABLE monitor_jobs DROP COLUMN IF EXISTS push_config")
    op.execute("ALTER TABLE monitor_jobs DROP COLUMN IF EXISTS pending_push_count")
