"""document user-overrides: 用户对 AI 生成字段的手动覆盖

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-20 18:00:00

动机：
- AI 生成的 one_line_summary / ai_key_points / ai_summary 可能有误
- 用户在卡片里手动编辑后，要保证 AI 重新跑不会覆盖用户修改
- 策略：双字段 (_ai 保留 + _user 用户编辑)；展示时优先 _user，缺省用 _ai
"""
from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("one_line_summary_user", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("ai_key_points_user", sa.ARRAY(sa.Text()), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("ai_summary_user", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "ai_summary_user")
    op.drop_column("documents", "ai_key_points_user")
    op.drop_column("documents", "one_line_summary_user")
