# ──────── Application logging（必须在任何 app.* import 之前）────────
# uvicorn 默认只配置了 uvicorn.* logger；app.* 的 logger.info() 被 root logger
# WARNING level 吞掉。这里单独给 "app" namespace 配 stdout handler，
# 不动 root/uvicorn 自己的配置，避免 access log 重复。
import logging as _logging

def _init_app_logging():
    _app_logger = _logging.getLogger("app")
    _app_logger.setLevel(_logging.INFO)
    # 清除已有 handler（热重启场景）
    for _h in list(_app_logger.handlers):
        _app_logger.removeHandler(_h)
    _handler = _logging.StreamHandler()
    _handler.setFormatter(_logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    ))
    _app_logger.addHandler(_handler)
    _app_logger.propagate = False  # 避免重复 + 不污染 root

_init_app_logging()
# ──────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import auth, projects, search, feedback, llm, skills, ai_assist, stream, classification, monitoring, devtools, conversation, knowledge_graph, collaboration, library, notebook as notebook_api, features as features_api, session_exit as session_exit_api, document_import as document_import_api, site_feedback, memory as memory_api, admin_invitations, admin_users, telemetry as telemetry_api, user_documents as user_documents_api
from app.services.fetchers.base import FetcherRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭生命周期"""
    print(f"[{settings.app_name}] 启动中...")
    # 初始化 LLM 管理器（单例 + Redis 缓存）
    from app.services.core.llm_config_store import get_llm_manager
    manager = await get_llm_manager()
    print(f"[LLM] 活跃提供商: {manager.active_provider_id}（已配置 {len(manager.providers)} 个）")

    # DevTools: patch LLM manager for call logging
    from app.services.devtools.llm_logger import patch_llm_manager
    patch_llm_manager(manager)

    # 初始化 Harness Engineering 组件 —— 统一入口 bootstrap.setup_harness()
    # 同时被 celery_app.worker_process_init 调用，确保 backend + worker 永远同步
    from app.harness.bootstrap import setup_harness
    counts = setup_harness()
    print(f"[Harness] Tool Registry: {counts['tools']} tools | Hook Engine: {counts['hooks']} handlers | Skills: {counts['skills']}")

    # SKILL.md 加载: 用户/管理员定义的 markdown persona skills
    # 失败不阻断启动 (LLM 仍可用原 prompt 跑)
    try:
        from app.harness.skill_registry import SkillRegistry
        from app.harness.skills.markdown_loader import register_markdown_skills
        md_n = await register_markdown_skills(SkillRegistry.get_instance())
        print(f"[Harness] Markdown Skills: {md_n} loaded from .md files")
    except Exception as _md_err:
        print(f"[Harness] Markdown skill load failed (non-fatal): {_md_err}")

    # DevTools: start periodic log buffer flush
    from app.services.devtools.log_writer import log_buffer
    await log_buffer.start_periodic_flush()
    print("[DevTools] Log buffer started")

    yield

    # DevTools: flush remaining logs
    await log_buffer.stop()
    print(f"[{settings.app_name}] 关闭中...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="面向科研人员的全领域情报检索平台",
    lifespan=lifespan,
)

# CORS: credentials=True 下浏览器不接受通配符 Origin，必须显式枚举。
# 生产环境务必在 .env 里配置 cors_allowed_origins（逗号分隔），
# 空值降级为 ["*"] + credentials=False 以保持最小可用。
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

from app.middleware.request_logger import RequestLoggerMiddleware
app.add_middleware(RequestLoggerMiddleware)

from app.middleware.client_meta import ClientMetaMiddleware
app.add_middleware(ClientMetaMiddleware)

# M3: BYOK 透传 — 解析 X-User-LLM-* header → request.state.user_llm_override
from app.middleware.client_llm_override import ClientLLMOverrideMiddleware
app.add_middleware(ClientLLMOverrideMiddleware)

# 注册路由
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(search.router)
app.include_router(feedback.router)
app.include_router(llm.router)
app.include_router(skills.router)
app.include_router(ai_assist.router)
app.include_router(stream.router)
app.include_router(classification.router)
app.include_router(monitoring.router)
app.include_router(devtools.router)
app.include_router(conversation.router)
app.include_router(collaboration.router)
app.include_router(knowledge_graph.router)
app.include_router(library.router)
app.include_router(notebook_api.router)
app.include_router(features_api.router)
app.include_router(session_exit_api.router)
app.include_router(document_import_api.router)
app.include_router(site_feedback.router)
app.include_router(memory_api.router)
app.include_router(admin_invitations.router)
app.include_router(admin_users.router)
app.include_router(telemetry_api.router)
# 0028: per-user-per-document ownership（多设备 PDF 同步基础设施）
app.include_router(user_documents_api.users_router)
app.include_router(user_documents_api.projects_router)


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": settings.app_version, "status": "running"}


@app.get("/health")
async def health():
    from app.services.core.llm_config_store import get_llm_manager
    from app.harness.tool_registry import ToolRegistry
    from app.harness.hooks.metrics_hook import get_metrics
    llm_status = await (await get_llm_manager()).check_active_connection()
    registry = ToolRegistry.get_instance()
    return {
        "status": "ok",
        "llm": llm_status,
        "sources": FetcherRegistry.get_all_info(),
        "harness": {
            "tool_registry": registry.get_all_stats(),
            "metrics": get_metrics(),
        },
    }


# M3 dev/test-only echo route — 仅当 ENV ENABLE_TEST_ECHO_ROUTES=1 时存在
# 生产 env 必须保持未设或 =0，避免暴露 request.state
import os as _os
if _os.environ.get("ENABLE_TEST_ECHO_ROUTES") == "1":
    from fastapi import Request as _R

    @app.get("/api/_test/byok-echo")
    async def _test_byok_echo(request: _R):
        """Return request.state.user_llm_override for middleware testing."""
        return {"user_llm_override": getattr(request.state, "user_llm_override", None)}
