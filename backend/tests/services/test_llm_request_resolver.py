import pytest
from starlette.requests import Request

from app.services.core.llm_request_resolver import (
    get_llm_for_request,
    _build_temp_provider,
)


def _mock_request(user_llm_override=None):
    """Construct a minimal Request stub with only state.user_llm_override set."""
    scope = {
        "type": "http",
        "headers": [],
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    req = Request(scope)
    req.state.user_llm_override = user_llm_override
    return req


@pytest.mark.asyncio
async def test_no_override_returns_global_provider():
    """No override → fall back to global manager.active_provider (web user path)."""
    req = _mock_request(user_llm_override=None)
    provider = await get_llm_for_request(req)
    assert provider is not None
    assert hasattr(provider, "generate_full")


@pytest.mark.asyncio
async def test_byok_override_returns_temp_provider_with_key():
    """Override present → temp provider carrying BYOK key in config."""
    req = _mock_request(user_llm_override={
        "provider": "openai",
        "api_key": "sk-test-byok",
        "model": "gpt-4o",
        "base_url": None,
    })
    provider = await get_llm_for_request(req)
    assert provider.api_key == "sk-test-byok"
    assert provider.model == "gpt-4o"


@pytest.mark.asyncio
async def test_byok_override_does_not_pollute_global_singleton():
    """Temp provider must not write back to the global LLMManager cache."""
    from app.services.core.llm_config_store import get_llm_manager

    manager_before = await get_llm_manager()
    active_before = manager_before.get_active_provider()

    req = _mock_request(user_llm_override={
        "provider": "openai", "api_key": "sk-x", "model": None, "base_url": None,
    })
    _ = await get_llm_for_request(req)

    manager_after = await get_llm_manager()
    assert manager_after.get_active_provider() is active_before, (
        "global active_provider should not be replaced by per-request BYOK"
    )


@pytest.mark.asyncio
async def test_unknown_provider_falls_back_to_global():
    """Defence-in-depth: even if state somehow has unknown provider, fall back."""
    req = _mock_request(user_llm_override={
        "provider": "evilcorp", "api_key": "sk-x", "model": None, "base_url": None,
    })
    provider = await get_llm_for_request(req)
    # Provider should NOT be a temp BYOK one — it's the global active.
    assert getattr(provider, "api_key", None) != "sk-x"


def test_build_temp_provider_deepseek_auto_base_url():
    """Provider 'deepseek' without explicit base_url → auto-fill DeepSeek endpoint."""
    p = _build_temp_provider({
        "provider": "deepseek", "api_key": "sk-ds", "model": None, "base_url": None,
    })
    assert p is not None
    assert "deepseek.com" in p.base_url


def test_build_temp_provider_custom_requires_base_url():
    """Provider 'custom' without base_url → None."""
    p = _build_temp_provider({
        "provider": "custom", "api_key": "sk-x", "model": None, "base_url": None,
    })
    assert p is None
