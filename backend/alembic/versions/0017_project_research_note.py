"""project.research_note_md / research_note_updated_at / research_note_updated_by

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-19 12:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "research_note_md",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "research_note_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "research_note_updated_by",
            sa.String(10),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "research_note_updated_by")
    op.drop_column("projects", "research_note_updated_at")
    op.drop_column("projects", "research_note_md")
