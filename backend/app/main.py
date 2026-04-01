from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import auth, projects, search, feedback, llm, skills, ai_assist, stream
from app.services.fetchers.base import FetcherRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭生命周期"""
    print(f"[{settings.app_name}] 启动中...")
    # 初始化 LLM 管理器，并从 Redis 恢复已保存的配置
    from app.api.llm import get_llm_manager
    from app.services.core.llm_config_store import load_llm_config
    manager = get_llm_manager()
    loaded = await load_llm_config(manager, settings.redis_url)
    if loaded:
        print(f"[LLM] 已从 Redis 恢复配置，当前活跃提供商: {manager.active_provider_id}")
    else:
        print("[LLM] 提供商管理器已初始化（使用默认配置）")

    # 初始化 Harness Engineering 组件
    from app.harness.tool_registry import init_tool_registry
    from app.harness.hook_engine import HookEngine
    from app.harness.hooks.logging_hook import register_logging_hooks
    from app.harness.hooks.metrics_hook import register_metrics_hooks
    tool_registry = init_tool_registry()
    hook_engine = HookEngine.get_instance()
    register_logging_hooks(hook_engine)
    register_metrics_hooks(hook_engine)
    # Register skills
    from app.harness.skill_registry import SkillRegistry
    from app.harness.skills import deep_dive, trend_spotter, gap_finder
    skill_registry = SkillRegistry.get_instance()
    skill_registry.register(deep_dive.DEFINITION, deep_dive.execute)
    skill_registry.register(trend_spotter.DEFINITION, trend_spotter.execute)
    skill_registry.register(gap_finder.DEFINITION, gap_finder.execute)

    print(f"[Harness] Tool Registry: {tool_registry.enabled_count} tools | Hook Engine: {hook_engine.handler_count} handlers | Skills: {skill_registry.skill_count}")

    yield
    print(f"[{settings.app_name}] 关闭中...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="面向科研人员的全领域情报检索平台",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(search.router)
app.include_router(feedback.router)
app.include_router(llm.router)
app.include_router(skills.router)
app.include_router(ai_assist.router)
app.include_router(stream.router)


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": settings.app_version, "status": "running"}


@app.get("/health")
async def health():
    from app.api.llm import get_llm_manager
    from app.harness.tool_registry import ToolRegistry
    from app.harness.hooks.metrics_hook import get_metrics
    llm_status = await get_llm_manager().check_active_connection()
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
