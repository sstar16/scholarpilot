"""
LLM 提供商配置 API（与 v1 功能相同，接口一致）
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user
from app.models.user import User
from app.config import settings
from app.services.core.llm_config_store import save_llm_config, load_llm_config

router = APIRouter(prefix="/api/llm", tags=["llm"])

# 全局 LLM 管理器
_llm_manager = None
_llm_loaded_from_redis = False


def get_llm_manager():
    global _llm_manager, _llm_loaded_from_redis
    if _llm_manager is None:
        from app.services.core.llm_providers import LLMProviderManager
        _llm_manager = LLMProviderManager(default_ollama_host=settings.ollama_host)
    # 首次使用时从 Redis 恢复已保存的配置
    if not _llm_loaded_from_redis:
        _llm_loaded_from_redis = True
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在 async 上下文中（FastAPI 请求），用 create_task 延迟加载
                # 但这里需要同步返回，所以用标记+首次 list 时加载
                pass
            else:
                loop.run_until_complete(load_llm_config(_llm_manager, settings.redis_url))
        except Exception:
            pass
    return _llm_manager


async def _ensure_loaded():
    """确保 Redis 配置已加载（在 async 上下文中调用）"""
    global _llm_manager, _llm_loaded_from_redis
    mgr = get_llm_manager()
    if _llm_loaded_from_redis and len(mgr.providers) <= 1:
        # 可能首次同步加载失败，async 重试
        await load_llm_config(mgr, settings.redis_url)
    return mgr


class ProviderConfig(BaseModel):
    provider_id: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    host: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: Optional[int] = None


@router.get("/providers")
async def list_providers(current_user: User = Depends(get_current_user)):
    manager = await _ensure_loaded()
    return {"providers": manager.get_available_providers(), "active": manager.active_provider_id}


@router.post("/configure")
async def configure_provider(
    req: ProviderConfig,
    current_user: User = Depends(get_current_user),
):
    manager = await _ensure_loaded()
    config = {}
    if req.api_key:
        config["api_key"] = req.api_key
    if req.model:
        config["model"] = req.model
    if req.host:
        config["host"] = req.host
    if req.base_url:
        config["base_url"] = req.base_url
    if req.max_tokens is not None:
        config["max_tokens"] = req.max_tokens
    result = manager.configure_provider(req.provider_id, config)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    await save_llm_config(manager, settings.redis_url)
    return result


@router.post("/switch/{provider_id}")
async def switch_provider(
    provider_id: str,
    current_user: User = Depends(get_current_user),
):
    manager = await _ensure_loaded()
    result = manager.set_active_provider(provider_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    await save_llm_config(manager, settings.redis_url)
    return result


@router.delete("/{provider_id}")
async def remove_provider(
    provider_id: str,
    current_user: User = Depends(get_current_user),
):
    manager = await _ensure_loaded()
    result = manager.remove_provider(provider_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    await save_llm_config(manager, settings.redis_url)
    return result


@router.get("/test")
async def test_connection(current_user: User = Depends(get_current_user)):
    manager = await _ensure_loaded()
    status = await manager.check_active_connection()
    return status
