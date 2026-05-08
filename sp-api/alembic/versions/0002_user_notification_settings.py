"""user_notification_settings table

Revision ID: 0002_user_notif
Revises: 0001_sp_api_initial
Create Date: 2026-05-08

新增 user_notification_settings 表，存用户配置的推送通道（飞书/微信 Server酱/邮件/Telegram）。
config_json 存 channel-specific 配置（webhook URL / send key / SMTP creds），
敏感字段（webhook URL / send_key / smtp_password）应用层加密后再写入。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "0002_user_notif"
down_revision = "0001_sp_api_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notification_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("config_json", JSONB(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "channel",
            name="uq_user_notification_settings_user_channel",
        ),
        sa.CheckConstraint(
            "channel IN ('feishu', 'serverchan', 'email', 'telegram', "
            "'wxpusher', 'pushplus', 'wecom')",
            name="ck_user_notification_settings_channel",
        ),
    )
    op.create_index(
        "ix_user_notification_settings_user_id",
        "user_notification_settings",
        ["user_id"],
    )
    op.create_index(
        "ix_user_notification_settings_active",
        "user_notification_settings",
        ["user_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_notification_settings_active",
        table_name="user_notification_settings",
    )
    op.drop_index(
        "ix_user_notification_settings_user_id",
        table_name="user_notification_settings",
    )
    op.drop_table("user_notification_settings")
