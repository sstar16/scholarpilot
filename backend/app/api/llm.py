"""
LLM 提供商配置 API（与 v1 功能相同，接口一致）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user
from app.models.user import User
from app.config import settings
from app.services.core.llm_config_store import save_llm_config, load_llm_config

router = APIRouter(prefix="/api/llm", tags=["llm"])

# 全局 LLM 管理器（在 main.py 的 lifespan 中初始化）
_llm_manager = None


def get_llm_manager():
    global _llm_manager
    if _llm_manager is None:
        from app.services.core.llm_providers import LLMProviderManager
        _llm_manager = LLMProviderManager(default_ollama_host=settings.ollama_host)
    return _llm_manager


class ProviderConfig(BaseModel):
    provider_id: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    host: Optional[str] = None
    base_url: Optional[str] = None


@router.get("/providers")
async def list_providers(current_user: User = Depends(get_current_user)):
    manager = get_llm_manager()
    return {"providers": manager.get_available_providers(), "active": manager.active_provider_id}


@router.post("/configure")
async def configure_provider(
    req: ProviderConfig,
    current_user: User = Depends(get_current_user),
):
    manager = get_llm_manager()
    config = {}
    if req.api_key:
        config["api_key"] = req.api_key
    if req.model:
        config["model"] = req.model
    if req.host:
        config["host"] = req.host
    if req.base_url:
        config["base_url"] = req.base_url
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
    manager = get_llm_manager()
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
    manager = get_llm_manager()
    result = manager.remove_provider(provider_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    await save_llm_config(manager, settings.redis_url)
    return result


@router.get("/test")
async def test_connection(current_user: User = Depends(get_current_user)):
    manager = get_llm_manager()
    status = await manager.check_active_connection()
    return status
