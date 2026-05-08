"""add search_rounds.cancelled fields

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-17 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_rounds",
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "search_rounds",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("search_rounds", "cancelled_at")
    op.drop_column("search_rounds", "cancelled_reason")
