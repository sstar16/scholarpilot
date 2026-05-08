"""add user_profiles.auto_recipe_md / recipe_updated_at

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-27

每次 4 桶反馈完成后由 Memory Agent 自动生成的项目食谱
（来源命中率 / 关键词信号 / 主题簇 / 给下游 agent 的指引）。
与已有的 user_profiles.project_markdown（用户手编 + 对话增补）并列：
- project_markdown ：人工 / LLM-from-conversation，长期累积
- auto_recipe_md   ：纯统计 + 模板，每轮反馈 regenerate
两者通过 build_combined_memory_for_agents 一并喂给 agents。
"""
from alembic import op
import sqlalchemy as sa


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("auto_recipe_md", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("recipe_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "recipe_updated_at")
    op.drop_column("user_profiles", "auto_recipe_md")
