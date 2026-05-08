"""UserNotificationSetting — 用户配置的推送通道。

每个 user × channel 一行；config_json 存 channel-specific 配置：
- feishu: {"webhook_url_enc": "<encrypted>"}
- serverchan: {"send_key_enc": "<encrypted>"}
- email: {"address": "...", "smtp_host": "...", ...} (smtp_password_enc 单独字段)
- telegram: {"chat_id": "..."}
- wxpusher: {"app_token_enc": "<encrypted>", "uid": "..."}
- pushplus: {"token_enc": "<encrypted>"}
- wecom: {"webhook_url_enc": "<encrypted>"}

敏感字段以 _enc 后缀加密存（参见 services/notifications/crypto.py）。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# 与 alembic CheckConstraint 保持一致
ALLOWED_CHANNELS = (
    "feishu",
    "serverchan",
    "email",
    "telegram",
    "wxpusher",
    "pushplus",
    "wecom",
)


class UserNotificationSetting(Base):
    __tablename__ = "user_notification_settings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "channel",
            name="uq_user_notification_settings_user_channel",
        ),
        CheckConstraint(
            "channel IN ('feishu', 'serverchan', 'email', 'telegram', "
            "'wxpusher', 'pushplus', 'wecom')",
            name="ck_user_notification_settings_channel",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # 加密后的 channel 配置；明文不入 DB
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
