"""sp-api ORM 模型 — 8 张表（user / invitation_code / refresh_token / dev_log /
site_feedback / document_import_job / user_document / user_notification_setting）。

vs backend/app/models 删除：
  - project / search_round / round_document / document / feedback /
    user_profile / monitor_job / monitoring_push / document_classification /
    conversation_session / user_feedback (PRJ 反馈) / user_memory
  - 仅保留 site_feedback（首页反馈按钮，原 user_feedback 表 → 改名 site_feedback）
"""
from app.models.user import User
from app.models.invitation_code import InvitationCode
from app.models.refresh_token import RefreshToken
from app.models.dev_log import DevLog
from app.models.site_feedback import SiteFeedback
from app.models.document_import_job import DocumentImportJob
from app.models.user_document import UserDocument
from app.models.user_notification_setting import UserNotificationSetting

__all__ = [
    "User",
    "InvitationCode",
    "RefreshToken",
    "DevLog",
    "SiteFeedback",
    "DocumentImportJob",
    "UserDocument",
    "UserNotificationSetting",
]
