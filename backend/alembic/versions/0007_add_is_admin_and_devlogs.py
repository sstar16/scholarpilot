"""add is_admin to users + create dev_logs table

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-07
"""
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users 表添加 is_admin 字段
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE")

    # 2. 创建 dev_logs 表
    op.execute("""
        CREATE TABLE IF NOT EXISTS dev_logs (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            level VARCHAR(10) NOT NULL,
            source VARCHAR(30) NOT NULL,
            category VARCHAR(200),
            message TEXT NOT NULL,
            context JSONB,
            round_id UUID,
            project_id UUID,
            duration_ms INTEGER,
            error_trace TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_devlogs_created ON dev_logs(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_devlogs_level ON dev_logs(level)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_devlogs_source ON dev_logs(source)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_devlogs_round ON dev_logs(round_id) WHERE round_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dev_logs CASCADE")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_admin")
