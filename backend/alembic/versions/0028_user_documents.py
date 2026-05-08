"""add user_documents table

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-02

per-user-per-document-per-project ownership 表，让多设备登录后能感知用户
"之前下载/上传过哪些 PDF/HTML"，触发静默批量同步。spec 见
docs/spec-pdf-ownership-sync.md。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column(
            "owned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "document_id", "project_id", "format",
            name="uq_user_documents_user_doc_project_format",
        ),
    )
    op.create_index("ix_user_documents_user_id", "user_documents", ["user_id"])
    op.create_index("ix_user_documents_document_id", "user_documents", ["document_id"])
    op.create_index("ix_user_documents_project_id", "user_documents", ["project_id"])
    op.create_index(
        "ix_user_documents_user_project",
        "user_documents",
        ["user_id", "project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_documents_user_project", table_name="user_documents")
    op.drop_index("ix_user_documents_project_id", table_name="user_documents")
    op.drop_index("ix_user_documents_document_id", table_name="user_documents")
    op.drop_index("ix_user_documents_user_id", table_name="user_documents")
    op.drop_table("user_documents")
