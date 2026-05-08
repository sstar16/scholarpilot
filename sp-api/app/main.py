"""sp-api FastAPI 入口。

vs backend/app/main.py 关键差异：
- /health 不调 LLM manager（sp-api 无 LLM）
- lifespan 不 init harness / skill registry
- 不挂 ClientLLMOverrideMiddleware（BYOK 全在客户端）
- ClientMetaMiddleware 增强：MIN_CLIENT_VERSION 拦截（426 Upgrade Required）
"""
import logging as _logging


def _init_app_logging():
    _app_logger = _logging.getLogger("app")
    _app_logger.setLevel(_logging.INFO)
    for _h in list(_app_logger.handlers):
        _app_logger.removeHandler(_h)
    _handler = _logging.StreamHandler()
    _handler.setFormatter(_logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    ))
    _app_logger.addHandler(_handler)
    _app_logger.propagate = False


_init_app_logging()


from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from prometheus_fastapi_instrumentator import Instrumentator

from app.api import (
    admin_invitations,
    admin_users,
    auth,
    fetcher,
    fulltext,
    notifications,
    site_feedback,
    stream,
    telemetry,
    user_documents,
)
from app.config import settings
from app.middleware.client_meta import ClientMetaMiddleware
from app.middleware.request_logger import RequestLoggerMiddleware
from app.services.health_cache import get_cached_sources

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    strategy="fixed-window",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[{settings.app_name}] 启动中...")

    # DevTools log buffer 周期性 flush（写 dev_logs 表）
    from app.services.devtools.log_writer import log_buffer
    await log_buffer.start_periodic_flush()
    print("[DevTools] Log buffer started")

    yield

    await log_buffer.stop()
    print(f"[{settings.app_name}] 关闭中...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="ScholarPilot HK client-only backend (fetcher + fulltext bridge)",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — 客户端走 Tauri origin（http://tauri.localhost）；空字符串降级到 *
_cors_raw = (settings.cors_allowed_origins or "").strip()
if _cors_raw:
    _allow_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    _allow_credentials = True
else:
    _allow_origins = ["*"]
    _allow_credentials = False
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SlowAPIASGIMiddleware 在 ClientMetaMiddleware 前（先限流再鉴权）
app.add_middleware(SlowAPIASGIMiddleware)
app.add_middleware(RequestLoggerMiddleware)
app.add_middleware(ClientMetaMiddleware)

# Prometheus metrics — 暴露 /metrics 端点（Instrumentator 自动注册路由）
Instrumentator().instrument(app).expose(app)


# ─── 路由 ─────────────────────────────────────────
app.include_router(auth.router)
app.include_router(admin_invitations.router)
app.include_router(admin_users.router)
app.include_router(telemetry.router)
app.include_router(site_feedback.router)
app.include_router(fetcher.router)
app.include_router(fulltext.router)
app.include_router(stream.router)
app.include_router(user_documents.users_router)
app.include_router(user_documents.projects_router)
app.include_router(notifications.router)


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": settings.app_version, "status": "running"}


@app.get("/health")
async def health():
    """Health check — 不返 LLM 字段（V9 验收）。sources 列表走 5min 缓存减重复循环。"""
    return {
        "status": "ok",
        "version": settings.app_version,
        "sources": await get_cached_sources(),
    }


# 同时挂 /api/health（客户端可能用这个 path）
@app.get("/api/health")
async def api_health():
    return await health()
