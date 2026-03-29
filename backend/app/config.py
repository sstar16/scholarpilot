from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 数据库
    database_url: str = "postgresql+asyncpg://urip:password@localhost:5432/urip"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str = "change_me_in_production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 天

    # LLM
    ollama_host: str = "http://localhost:11434"

    # 文件存储
    pdf_storage_path: str = "./data/pdfs"
    export_path: str = "./data/exports"

    # Unpaywall
    unpaywall_email: str = "user@example.com"

    # Lens.org 专利 API（免费，https://www.lens.org/lens/user/subscriptions 申请）
    lens_api_token: str = ""

    # 应用
    debug: bool = False
    app_name: str = "URIP - 科研情报平台"
    app_version: str = "1.0.0"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
