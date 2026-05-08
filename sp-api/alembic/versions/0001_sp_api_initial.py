"""sp-api initial schema (7 tables)

Revision ID: 0001_sp_api_initial
Revises:
Create Date: 2026-05-08

7 张表：
  users / invitation_codes / refresh_tokens / dev_logs /
  site_feedback / document_import_jobs / user_documents

不继承 backend 0001-0028（schema 完全独立，避免 backend orm 字段串台）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "0001_sp_api_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ───────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("hashed_pw", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("is_admin", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── invitation_codes ────────────────────────────────────
    op.create_table(
        "invitation_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "used_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_invitation_codes_code", "invitation_codes", ["code"], unique=True)

    # ── refresh_tokens ──────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("client_type", sa.String(32), nullable=False, server_default="desktop"),
        sa.Column("client_version", sa.String(32), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    # ── dev_logs ────────────────────────────────────────────
    op.create_table(
        "dev_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("category", sa.String(200), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", JSONB(), nullable=True),
        sa.Column("round_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_trace", sa.Text(), nullable=True),
    )
    op.create_index("ix_dev_logs_created_at", "dev_logs", ["created_at"])
    op.create_index("ix_dev_logs_level", "dev_logs", ["level"])
    op.create_index("ix_dev_logs_source", "dev_logs", ["source"])

    # ── site_feedback ───────────────────────────────────────
    op.create_table(
        "site_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_email_snapshot", sa.String(255), nullable=True),
        sa.Column("category", sa.String(32), nullable=False, server_default="other"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("contact", sa.String(255), nullable=True),
        sa.Column("page_url", sa.String(500), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "category IN ('bug', 'suggestion', 'praise', 'other')",
            name="ck_site_feedback_category",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'triaged', 'resolved', 'wontfix')",
            name="ck_site_feedback_status",
        ),
    )
    op.create_index("ix_site_feedback_user_id", "site_feedback", ["user_id"])

    # ── document_import_jobs ────────────────────────────────
    op.create_table(
        "document_import_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("metadata_draft", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_document_import_jobs_project_id", "document_import_jobs", ["project_id"])
    op.create_index("ix_document_import_jobs_session_id", "document_import_jobs", ["session_id"])

    # ── user_documents ──────────────────────────────────────
    op.create_table(
        "user_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column(
            "owned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "document_id", "project_id", "format",
            name="uq_user_documents_user_doc_project_format",
        ),
    )
    op.create_index("ix_user_documents_user_id", "user_documents", ["user_id"])
    op.create_index("ix_user_documents_document_id", "user_documents", ["document_id"])
    op.create_index("ix_user_documents_project_id", "user_documents", ["project_id"])


def downgrade() -> None:
    op.drop_table("user_documents")
    op.drop_table("document_import_jobs")
    op.drop_table("site_feedback")
    op.drop_table("dev_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("invitation_codes")
    op.drop_table("users")
