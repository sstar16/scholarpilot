"""document import jobs table + documents.import_source/imported_at

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-17 18:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # documents: import_source + imported_at
    op.add_column(
        "documents",
        sa.Column(
            "import_source", sa.String(30),
            nullable=False, server_default="search",
        ),
    )
    op.add_column(
        "documents",
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_documents_import_source",
        "documents", ["import_source"],
    )

    # document_import_jobs
    op.create_table(
        "document_import_jobs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True, server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "document_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column(
            "status", sa.String(30), nullable=False,
            comment="parsing|awaiting_edit|scoring|ready|failed|cancelled",
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("metadata_draft", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_import_jobs_session_status",
        "document_import_jobs", ["session_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_import_jobs_session_status", "document_import_jobs")
    op.drop_table("document_import_jobs")
    op.drop_index("idx_documents_import_source", "documents")
    op.drop_column("documents", "imported_at")
    op.drop_column("documents", "import_source")
