"""create document_classifications table + migrate feedback data

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 创建 document_classifications 表
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_classifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES documents(id),
            bucket VARCHAR(20) NOT NULL,
            classified_in_round_id UUID REFERENCES search_rounds(id) ON DELETE SET NULL,
            reason TEXT,
            positive_signals JSONB,
            negative_signals JSONB,
            classified_at TIMESTAMPTZ DEFAULT now(),
            moved_at TIMESTAMPTZ,
            CONSTRAINT uq_user_doc_project_class UNIQUE (user_id, document_id, project_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_doc_class_user_id ON document_classifications(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_doc_class_project_id ON document_classifications(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_doc_class_document_id ON document_classifications(document_id)")

    # 2. 从 feedback 迁移数据到 document_classifications
    # 对于同一 (user, doc, project) 有多条反馈的，保留最新一条
    op.execute("""
        INSERT INTO document_classifications (user_id, project_id, document_id, bucket, classified_in_round_id, reason, positive_signals, negative_signals, classified_at)
        SELECT DISTINCT ON (f.user_id, f.document_id, f.project_id)
            f.user_id,
            f.project_id,
            f.document_id,
            CASE f.relevance
                WHEN 2 THEN 'very_relevant'
                WHEN 1 THEN 'relevant'
                WHEN 0 THEN 'uncertain'
                WHEN -1 THEN 'irrelevant'
            END,
            f.round_id,
            f.reason,
            f.positive_signals,
            f.negative_signals,
            f.created_at
        FROM feedback f
        ORDER BY f.user_id, f.document_id, f.project_id, f.created_at DESC
        ON CONFLICT DO NOTHING
    """)

    # 3. 取消轮次上限（0 = 无限制）
    op.execute("UPDATE projects SET max_rounds = 0 WHERE max_rounds > 0")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_classifications CASCADE")
    op.execute("UPDATE projects SET max_rounds = 5 WHERE max_rounds = 0")
