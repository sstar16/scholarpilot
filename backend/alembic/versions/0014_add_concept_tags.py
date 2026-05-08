"""add concept_tags column to documents

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-15 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "concept_tags",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_documents_concept_tags",
        "documents",
        ["concept_tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_documents_concept_tags", table_name="documents")
    op.drop_column("documents", "concept_tags")
