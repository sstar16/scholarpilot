"""
LLM 提供商配置 API
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user
from app.models.user import User
from app.config import settings
from app.services.core.llm_config_store import get_llm_manager, save_llm_config

router = APIRouter(prefix="/api/llm", tags=["llm"])


class ProviderConfig(BaseModel):
    provider_id: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    host: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: Optional[int] = None


@router.get("/providers")
async def list_providers(current_user: User = Depends(get_current_user)):
    manager = await get_llm_manager()
    return {"providers": manager.get_available_providers(), "active": manager.active_provider_id}


@router.post("/configure")
async def configure_provider(
    req: ProviderConfig,
    current_user: User = Depends(get_current_user),
):
    manager = await get_llm_manager()
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
    manager = await get_llm_manager()
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
    manager = await get_llm_manager()
    result = manager.remove_provider(provider_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    await save_llm_config(manager, settings.redis_url)
    return result


@router.get("/test")
async def test_connection(current_user: User = Depends(get_current_user)):
    manager = await get_llm_manager()
    status = await manager.check_active_connection()
    return status


# M3: 临时构造 BYOK provider 跑极简 prompt 验证 key 可用性
import time as _time
from app.schemas.byok import BYOKTestRequest, BYOKTestResponse
from app.services.core.llm_request_resolver import _build_temp_provider


@router.post("/test-byok", response_model=BYOKTestResponse)
async def test_byok_config(
    req: BYOKTestRequest,
    current_user: User = Depends(get_current_user),
) -> BYOKTestResponse:
    """临时构造 BYOK provider 测一次极简调用。

    NOTE: req.api_key 仅存在于函数栈帧，不写 DB / Redis / log。
    """
    override = {
        "provider": req.provider,
        "api_key": req.api_key,
        "model": req.model,
        "base_url": req.base_url,
    }
    provider = _build_temp_provider(override)
    if provider is None:
        return BYOKTestResponse(ok=False, error="provider_init_failed")

    t0 = _time.time()
    try:
        result = await provider.generate_full(
            prompt="Reply with the word OK.",
            temperature=0.0,
            max_tokens=10,
        )
    except Exception:
        # 不暴露 raw 错（防泄漏 key 在堆栈里）
        return BYOKTestResponse(ok=False, error="llm_call_failed")

    latency_ms = int((_time.time() - t0) * 1000)
    if result is None:
        return BYOKTestResponse(ok=False, error="llm_returned_none", latency_ms=latency_ms)

    sample = getattr(result, "text", None) or getattr(result, "content", None) or str(result)
    return BYOKTestResponse(
        ok=True,
        sample_response=sample[:200] if sample else None,
        latency_ms=latency_ms,
    )
