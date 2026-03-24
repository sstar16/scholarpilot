from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import auth, projects, search, feedback, llm
from app.services.fetchers.base import FetcherRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭生命周期"""
    print(f"[{settings.app_name}] 启动中...")
    # 初始化 LLM 管理器
    from app.api.llm import get_llm_manager
    get_llm_manager()
    print("[LLM] 提供商管理器已初始化")
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


@app.get("/")
async def root():
    return {"name": settings.app_name, "version": settings.app_version, "status": "running"}


@app.get("/health")
async def health():
    from app.api.llm import get_llm_manager
    llm_status = await get_llm_manager().check_active_connection()
    return {
        "status": "ok",
        "llm": llm_status,
        "sources": FetcherRegistry.get_all_info(),
    }
