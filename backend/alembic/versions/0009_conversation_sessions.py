"""add conversation_sessions table

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-10
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversation_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
            current_state VARCHAR(50) NOT NULL DEFAULT 'idle',
            state_data JSONB DEFAULT '{}',
            messages JSONB DEFAULT '[]',
            search_mode VARCHAR(20),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_convsess_user ON conversation_sessions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_convsess_project ON conversation_sessions(project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_sessions")
