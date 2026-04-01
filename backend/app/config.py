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

    # Harness Engineering
    enable_agent_planning: bool = True        # AI-driven search strategy (default ON)
    enable_autonomous_rounds: bool = True     # Agent decides when to stop (not fixed 5 rounds)
    enable_auto_skills: bool = True           # Agent auto-triggers skills (e.g. deep dive on high-score docs)
    agent_planning_provider: str = "deepseek" # Preferred LLM for agent planning (cheap)
    max_llm_cost_per_round: float = 0.10      # Hard budget ceiling per round (USD)
    max_autonomous_rounds: int = 15           # Safety cap for autonomous mode
    enable_per_source_keywords: bool = True   # Per-source keyword optimization + confirmation UI

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
