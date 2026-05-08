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
    # access token 24h（M1.T7 起：客户端通过 refresh token 续期，access 短期化）
    # 历史值 10080(7d) 仍向后兼容：已签发的 7d access 会自然过期（JWT 无状态）
    access_token_expire_minutes: int = 60 * 24
    # refresh token 30 天（M1.T6 起，桌面/移动客户端持有 refresh 续 access）
    refresh_token_expire_days: int = 30

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

    # Scoring Agent
    enable_scoring_agent: bool = True         # LLM-based per-doc scoring (replaces hardcoded formula)
    scoring_cutoff_default: float = 7.0       # Default cutoff line (0-10)
    scoring_agent_provider: str = ""          # Empty = use user's default LLM provider

    # B1: LLM Prompt Cache — Redis memoization for deterministic agent calls
    enable_llm_cache: bool = True             # 总开关。temperature ≤ 0.4 的调用自动缓存
    llm_cache_ttl_seconds: int = 7200         # 2h，够跨轮复用同一 profile+prompt

    # Smart Retrieve — 多路 diverse query + RRF 融合，增强本地 BM25 召回
    # 适用 LocalKBFetcher，单 query → LLM 生成 N 路 diverse → 并行 BM25 → RRF top-K
    enable_smart_retrieve: bool = True        # 总开关，关掉退化为单 query
    smart_retrieve_n_queries: int = 5         # diverse query 总数（含 base_query）
    smart_retrieve_per_query_limit: int = 60  # 每路 BM25 召回上限
    smart_retrieve_top_k: int = 100           # RRF 融合后 top-K

    # Local Knowledge Base
    kb_data_dir: str = "/app/data/knowledge_base"

    # PatentHub 单轮 PDF 预算（1 元/次），超额拒绝所有下载路径（用户/自动/AI），
    # 0 = 禁用（全拒绝）。守门 key: patenthub:pdf_budget:{round_id}，TTL 30 天。
    max_patenthub_pdf_per_round: int = 5

    # Staleness 主动提示：距上次完成轮次 >= 此天数时，进入项目时往对话流插
    # 一条 stale_hint 富消息（24h 去重；用户点忽略后 7 天内不再插）。
    stale_days_threshold: int = 7
    stale_dedup_hours: int = 24
    stale_dismiss_days: int = 7

    # 应用
    debug: bool = False
    app_name: str = "URIP - 科研情报平台"
    app_version: str = "1.0.0"

    # 用户反馈 Telegram 通知（可选；国内服务器被墙则留空，只入库）
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # API base —— 国内直连被墙，配成 Cloudflare Worker 反代 URL 即可
    # 例：https://tg.yourdomain.com（Worker 绑定的自定义域名；*.workers.dev 在国内被 DNS 污染用不了）
    telegram_api_base: str = "https://api.telegram.org"
    # 飞书群机器人 webhook（国内直连通畅；与 Telegram 双发，任一失败不影响另一个）
    feishu_webhook_url: str = ""
    # 管理页允许访问的邮箱（登录此账号才能看 /admin/feedback）
    feedback_admin_email: str = ""

    # CORS — 生产环境应显式列出允许的 Origin。逗号分隔，.env 里覆盖。
    # 空字符串时降级到 ["*"] 以兼容纯内网 dev（不建议生产使用）。
    cors_allowed_origins: str = (
        "http://localhost,"
        "http://localhost:5173,"
        "http://localhost:3000,"
        "http://127.0.0.1"
    )

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
