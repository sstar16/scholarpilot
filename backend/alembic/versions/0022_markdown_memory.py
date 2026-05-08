"""markdown_memory: 用户级 Markdown 记忆 + 项目级 Markdown 记忆

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-22

学习 Claude Code 的 .md 记忆机制：
- 新表 `user_memories`（user_id 唯一）：用户跨项目共享的身份/职业/通用偏好
- `user_profiles` 加字段 `project_markdown`：项目级的研究方向/关注点/已读重点文献

两份文本都是用户可见、可手动编辑的 Markdown；同时支持 LLM 从对话自动增补。
原 `memory_text` 字段保留（作为 agent 内部维护的非结构化快照，用户不直接编辑）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 新建 user_memories（用户级，一对一）
    op.create_table(
        "user_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("markdown_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 2) user_profiles 加 project_markdown
    op.add_column(
        "user_profiles",
        sa.Column("project_markdown", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "project_markdown")
    op.drop_table("user_memories")
