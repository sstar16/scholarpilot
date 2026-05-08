import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_test_byok_with_invalid_provider_returns_422(async_client: AsyncClient, auth_headers, db, test_user):
    await db.commit()  # ensure test_user persisted before async_client (independent session) auth check
    res = await async_client.post(
        "/api/llm/test-byok",
        headers=auth_headers,
        json={"provider": "evilcorp", "api_key": "sk-x"},
    )
    # Pydantic Literal validation rejects → 422
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_test_byok_provider_construct_failure_returns_init_failed(async_client: AsyncClient, auth_headers, db, test_user):
    await db.commit()
    """Mock _build_temp_provider 返回 None → ok=false, error='provider_init_failed'."""
    with patch(
        "app.api.llm._build_temp_provider",
        return_value=None,
    ):
        res = await async_client.post(
            "/api/llm/test-byok",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-test", "model": "fake-model"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "provider_init_failed"


@pytest.mark.asyncio
async def test_test_byok_llm_call_success_returns_sample(async_client: AsyncClient, auth_headers, db, test_user):
    await db.commit()
    """BYOK provider 构造成功 + LLM 调用成功 → 200 ok=true."""
    fake_provider = AsyncMock()
    fake_result = MagicMock()
    fake_result.text = "OK"
    fake_provider.generate_full = AsyncMock(return_value=fake_result)

    with patch(
        "app.api.llm._build_temp_provider",
        return_value=fake_provider,
    ):
        res = await async_client.post(
            "/api/llm/test-byok",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-test"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["sample_response"] == "OK"
    assert body["latency_ms"] is not None and body["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_test_byok_llm_call_failure_returns_error(async_client: AsyncClient, auth_headers, db, test_user):
    await db.commit()
    """LLM 调用抛异常 → 200 ok=false, error 简短分类不含 raw exception."""
    fake_provider = AsyncMock()
    fake_provider.generate_full = AsyncMock(side_effect=Exception("Some private error with sk-... in it"))

    with patch(
        "app.api.llm._build_temp_provider",
        return_value=fake_provider,
    ):
        res = await async_client.post(
            "/api/llm/test-byok",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-test"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "llm_call_failed"
    assert "sk-" not in (body.get("error") or "")
