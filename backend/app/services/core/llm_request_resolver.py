"""Per-request LLM provider resolver.

If the request has `state.user_llm_override` set (by ClientLLMOverrideMiddleware),
construct a temporary provider with the user's BYOK API key. Otherwise fall back
to the global singleton's active_provider.

The temporary provider is **not** cached or persisted anywhere — created fresh
per request and garbage-collected when the request finishes.
"""
import logging
from typing import Optional

from starlette.requests import Request

from app.services.core.llm_providers import (
    BaseLLMProvider,
    OpenAICompatibleProvider,
    AnthropicProvider,
)
from app.services.core.llm_config_store import get_llm_manager

logger = logging.getLogger(__name__)

# Default base_urls for OpenAI-compatible providers — keep in sync with
# llm_providers.py LLMProviderManager defaults at lines 719/731.
_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
}


def _build_temp_provider(override: dict) -> Optional[BaseLLMProvider]:
    """Construct a one-off provider from BYOK override config.

    Returns None for unrecognised provider strings (defence-in-depth — the
    middleware already filters but we don't trust state set elsewhere).
    """
    provider_name = override.get("provider")
    api_key = override.get("api_key")
    if not provider_name or not api_key:
        return None

    config: dict = {"api_key": api_key, "provider_name": provider_name}
    if override.get("model"):
        config["model"] = override["model"]
    if override.get("base_url"):
        config["base_url"] = override["base_url"]

    try:
        if provider_name == "anthropic":
            return AnthropicProvider(config)
        if provider_name in ("openai", "deepseek", "moonshot"):
            # OpenAI-compatible — auto-fill default base_url if user didn't provide
            if "base_url" not in config:
                config["base_url"] = _DEFAULT_BASE_URLS[provider_name]
            return OpenAICompatibleProvider(config)
        if provider_name == "custom":
            # User must supply base_url for 'custom'
            if not override.get("base_url"):
                return None
            return OpenAICompatibleProvider(config)
        return None
    except Exception as e:
        # Construct failure → silent fallback (don't leak key in logs)
        logger.warning("[llm_request_resolver] BYOK provider build failed: %s", type(e).__name__)
        return None


async def get_llm_for_request(request: Request) -> BaseLLMProvider:
    """Prefer BYOK override; fall back to global active_provider."""
    override = getattr(request.state, "user_llm_override", None)
    if override:
        temp = _build_temp_provider(override)
        if temp is not None:
            return temp
    manager = await get_llm_manager()
    return manager.get_active_provider()


async def get_llm_with_override(override: Optional[dict]) -> BaseLLMProvider:
    """Same as get_llm_for_request but accepts a plain dict instead of Request.

    Useful for service-layer code that doesn't have the FastAPI Request
    available (e.g. agents called from within a handler that already extracted
    the override).
    """
    if override:
        temp = _build_temp_provider(override)
        if temp is not None:
            return temp
    manager = await get_llm_manager()
    return manager.get_active_provider()
