"""user_feedback: 首页反馈按钮提交的用户产品反馈

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-21

用户在首页点"反馈"按钮提交的产品反馈（bug / 建议 / 其他），
和已有的 feedback 表（文献相关性）区分开。

提交后同步推送到 Telegram（由 services/telegram_notify.py 负责，配置缺失静默降级）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True, index=True,
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
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('bug', 'suggestion', 'praise', 'other')",
            name="ck_user_feedback_category",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'triaged', 'resolved', 'wontfix')",
            name="ck_user_feedback_status",
        ),
    )
    op.create_index(
        "ix_user_feedback_created_at", "user_feedback",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_user_feedback_created_at", table_name="user_feedback")
    op.drop_table("user_feedback")
