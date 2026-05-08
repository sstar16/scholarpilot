import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_no_byok_header_sets_override_none(async_client: AsyncClient):
    """没传 X-User-LLM-* header 时，override 应该是 None（即 web 用户路径）。"""
    res = await async_client.get("/api/_test/byok-echo")
    assert res.status_code == 200
    assert res.json()["user_llm_override"] is None


@pytest.mark.asyncio
async def test_full_byok_headers_parsed(async_client: AsyncClient):
    res = await async_client.get(
        "/api/_test/byok-echo",
        headers={
            "X-User-LLM-Provider": "openai",
            "X-User-LLM-Key": "sk-test-123",
            "X-User-LLM-Model": "gpt-4o",
            "X-User-LLM-Base-Url": "https://example.com/v1",
        },
    )
    body = res.json()
    assert body["user_llm_override"] == {
        "provider": "openai",
        "api_key": "sk-test-123",
        "model": "gpt-4o",
        "base_url": "https://example.com/v1",
    }


@pytest.mark.asyncio
async def test_partial_byok_provider_only_no_key_drops_override(async_client: AsyncClient):
    """只有 provider 没 key → 不设置 override（防止配错半套）。"""
    res = await async_client.get(
        "/api/_test/byok-echo",
        headers={"X-User-LLM-Provider": "openai"},
    )
    assert res.json()["user_llm_override"] is None


@pytest.mark.asyncio
async def test_unknown_provider_drops_override(async_client: AsyncClient):
    """未识别 provider 视为 None（防 header 注入未授权 SDK）。"""
    res = await async_client.get(
        "/api/_test/byok-echo",
        headers={
            "X-User-LLM-Provider": "evilcorp",
            "X-User-LLM-Key": "sk-x",
        },
    )
    assert res.json()["user_llm_override"] is None


@pytest.mark.asyncio
async def test_minimal_byok_provider_and_key_only(async_client: AsyncClient):
    """provider + key 是最小完整集。model/base_url 可省。"""
    res = await async_client.get(
        "/api/_test/byok-echo",
        headers={
            "X-User-LLM-Provider": "anthropic",
            "X-User-LLM-Key": "sk-ant-123",
        },
    )
    body = res.json()
    assert body["user_llm_override"]["provider"] == "anthropic"
    assert body["user_llm_override"]["api_key"] == "sk-ant-123"
    assert body["user_llm_override"]["model"] is None
    assert body["user_llm_override"]["base_url"] is None
