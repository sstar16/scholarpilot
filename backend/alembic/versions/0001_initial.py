"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 启用 pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("hashed_pw", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("domain", sa.String(100), nullable=False),
        sa.Column("current_round", sa.Integer, default=0),
        sa.Column("status", sa.String(20), default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    op.create_table(
        "search_rounds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), default="pending"),
        sa.Column("time_horizon_years", sa.Integer, nullable=True),
        sa.Column("max_results", sa.Integer, default=10),
        sa.Column("language_scope", sa.String(20), default="chinese"),
        sa.Column("sources_used", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("search_queries", postgresql.JSON, nullable=True),
        sa.Column("total_candidates", sa.Integer, default=0),
        sa.Column("selected_count", sa.Integer, default=0),
        sa.Column("progress", sa.Float, default=0.0),
        sa.Column("progress_message", sa.String(200), default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "round_number", name="uq_project_round"),
    )
    op.create_index("ix_search_rounds_project_id", "search_rounds", ["project_id"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("doc_type", sa.String(30), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("title_zh", sa.Text, nullable=True),
        sa.Column("authors", sa.Text, nullable=True),
        sa.Column("abstract", sa.Text, nullable=True),
        sa.Column("publication_date", sa.Date, nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("doi", sa.String(200), nullable=True),
        sa.Column("journal", sa.String(300), nullable=True),
        sa.Column("citation_count", sa.Integer, default=0),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("fulltext_status", sa.String(30), default="not_attempted"),
        sa.Column("fulltext_path", sa.String(500), nullable=True),
        sa.Column("fulltext_text", sa.Text, nullable=True),
        sa.Column("ai_summary", sa.Text, nullable=True),
        sa.Column("ai_key_points", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("ai_relevance_reason", sa.Text, nullable=True),
        sa.Column("ai_summary_source", sa.String(30), default="not_generated"),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("embedding", sa.Text, nullable=True),  # 存为 JSON 字符串，Phase 2 改为 vector
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source", "external_id", name="uq_source_external_id"),
    )
    op.create_index("ix_documents_source", "documents", ["source"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_publication_date", "documents", ["publication_date"])

    op.create_table(
        "round_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_rounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("rank_in_round", sa.Integer, nullable=True),
        sa.Column("initial_score", sa.Float, nullable=True),
        sa.UniqueConstraint("round_id", "document_id", name="uq_round_document"),
    )
    op.create_index("ix_round_documents_round_id", "round_documents", ["round_id"])

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("search_rounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("relevance", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("positive_signals", postgresql.JSON, nullable=True),
        sa.Column("negative_signals", postgresql.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("relevance IN (-1, 0, 1, 2)", name="ck_feedback_relevance"),
        sa.UniqueConstraint("user_id", "document_id", "round_id", name="uq_user_doc_round"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preferred_keywords", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("excluded_keywords", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("preferred_sources", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("preferred_doc_types", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("preferred_authors", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("feedback_count", sa.Integer, default=0),
        sa.Column("last_updated", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "project_id", name="uq_user_project_profile"),
    )

    op.create_table(
        "monitor_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("schedule", sa.String(20), default="daily"),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_config", postgresql.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "monitor_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("monitor_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True)),
        sa.Column("new_docs_found", sa.Integer, default=0),
        sa.Column("docs", postgresql.JSON, nullable=True),
        sa.Column("notified", sa.Boolean, default=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_monitor_results_job_id", "monitor_results", ["job_id"])


def downgrade() -> None:
    op.drop_table("monitor_results")
    op.drop_table("monitor_jobs")
    op.drop_table("user_profiles")
    op.drop_table("feedback")
    op.drop_table("round_documents")
    op.drop_table("documents")
    op.drop_table("search_rounds")
    op.drop_table("projects")
    op.drop_table("users")
