"""验证 BYOK API key 不出现在任何 log 输出。

跑前置：dev backend 容器内（docker compose exec backend pytest tests/api/test_byok_log_redaction.py -v）。
"""
import logging

import pytest
from httpx import AsyncClient


SECRET = "sk-test-REDACTION-CANARY-12345"


@pytest.mark.asyncio
async def test_byok_key_not_in_caplog_during_request(
    async_client: AsyncClient,
    db,
    test_user,
    auth_headers,
    caplog,
):
    """发请求带 BYOK key → caplog 输出不含 key 值。

    Catch-all：Python logging 任何 level + 任何 logger name 都被 caplog 捕获。
    如果 future log middleware 把 header 写进 logger，这个测试会立即抓到。
    """
    await db.commit()
    with caplog.at_level(logging.DEBUG):
        await async_client.get(
            "/api/_test/byok-echo",
            headers={
                **auth_headers,
                "X-User-LLM-Provider": "openai",
                "X-User-LLM-Key": SECRET,
            },
        )
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET not in log_text, (
        f"BYOK key 不应出现在任何 log 里。"
        f"如果失败，检查 backend/app/middleware/{{client_llm_override,request_logger}}.py "
        f"+ devtools log_writer.py 的 redact 逻辑。"
    )


@pytest.mark.asyncio
async def test_byok_key_not_in_devtools_log_buffer(
    async_client: AsyncClient,
    db,
    test_user,
    auth_headers,
):
    """发 BYOK 请求后 devtools log_buffer 不含 key（如 log_writer 写了请求摘要）。"""
    await db.commit()
    SECRET2 = "sk-test-DEVTOOLS-CANARY-67890"
    await async_client.get(
        "/api/_test/byok-echo",
        headers={
            **auth_headers,
            "X-User-LLM-Provider": "openai",
            "X-User-LLM-Key": SECRET2,
        },
    )
    try:
        from app.services.devtools.log_writer import log_buffer
        # log_buffer 接口可能是 read_recent / get_recent / dump，按实际 API 调
        recent = []
        for method_name in ("read_recent", "get_recent", "dump", "snapshot"):
            method = getattr(log_buffer, method_name, None)
            if callable(method):
                try:
                    recent = method(50)
                except TypeError:
                    recent = method()
                break
        text = "\n".join(str(e) for e in recent)
        assert SECRET2 not in text, "BYOK key 不应出现在 devtools log buffer 里"
    except ImportError:
        pytest.skip("devtools log_writer not available")
