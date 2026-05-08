"""sp-api Settings — 客户端 backend，无 LLM 字段。

vs backend/app/config.py 删除：
  ollama_host / enable_agent_planning / agent_planning_provider /
  max_llm_cost_per_round / max_autonomous_rounds / enable_per_source_keywords /
  enable_scoring_agent / scoring_cutoff_default / scoring_agent_provider /
  enable_llm_cache / llm_cache_ttl_seconds / enable_smart_retrieve /
  smart_retrieve_* / kb_data_dir / staleness_*

新增：
  min_client_version — < 此版本的 desktop 客户端访问被 426 拦截
  disable_fulltext_browser — 永远 True，sp-api 不带 chromium
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 数据库
    database_url: str = "postgresql+asyncpg://urip:password@localhost:5432/urip"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str = "change_me_in_production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    refresh_token_expire_days: int = 30

    # 文件存储
    pdf_storage_path: str = "./data/pdfs"

    # Unpaywall
    unpaywall_email: str = "scholarpilot@example.com"

    # 数据源凭证
    lens_api_token: str = ""
    epo_consumer_key: str = ""
    epo_consumer_secret: str = ""
    patenthub_api_token: str = ""

    # PatentHub 单轮 PDF 预算
    max_patenthub_pdf_per_round: int = 5

    # 反馈通知
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    feishu_webhook_url: str = ""
    feedback_admin_email: str = ""

    # 用户推送通道（V1：飞书 / Server酱 / 邮件 / Telegram）
    # 加密用 Fernet key（base64-encoded 32 bytes）；空字符串表示用 secret_key 派生（仅 dev）
    notification_secret: str = ""
    # SMTP 默认配置（用户配 email channel 时，可不填 SMTP，走平台默认）
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_from_name: str = "ScholarPilot"
    smtp_use_tls: bool = True
    # outbound HTTP user-agent（被对方 ban 时方便加白名单）
    notification_user_agent: str = "ScholarPilot-Notify/0.1"

    # 客户端版本拦截 — < 此版本 desktop 拒绝服务
    min_client_version: str = "0.2.0"

    # Browser fallback 永久关
    disable_fulltext_browser: bool = True

    # DB 连接池（高并发调优）
    db_pool_size: int = 20
    db_max_overflow: int = 30
    db_pool_timeout: int = 30

    # 应用
    debug: bool = False
    app_name: str = "ScholarPilot API (sp-api)"
    app_version: str = "0.1.0"

    # CORS — 客户端走 Tauri origin，预留可加
    cors_allowed_origins: str = ""


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
