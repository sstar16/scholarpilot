"""ClientMetaMiddleware tests — 验证 X-Client-Type/Version 解析到 request.state。

直接验证 middleware 内部逻辑（VALID_CLIENT_TYPES 收敛 + state 写入），
+ smoke test 通过现有 endpoint 确认 middleware 不破坏请求。
"""
import pytest
from httpx import AsyncClient
from starlette.requests import Request

from app.middleware.client_meta import VALID_CLIENT_TYPES, ClientMetaMiddleware


def _make_request(headers: dict[str, str]) -> Request:
    """构造一个最小 starlette Request 对象（仅 header 用，不调路由）。
    Starlette ASGI scope 要求 headers key 必须是 lowercase bytes。"""
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in headers.items()
    ]
    scope = {
        "type": "http",
        "headers": raw_headers,
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_middleware_parses_valid_client_type():
    captured: dict = {}

    async def call_next(request):
        captured["client_type"] = request.state.client_type
        captured["client_version"] = request.state.client_version
        # 返回 dummy response（middleware 不关心内容）
        from starlette.responses import Response
        return Response("ok")

    mw = ClientMetaMiddleware(app=None)
    req = _make_request({"X-Client-Type": "desktop", "X-Client-Version": "0.1.0"})
    await mw.dispatch(req, call_next)
    assert captured["client_type"] == "desktop"
    assert captured["client_version"] == "0.1.0"


@pytest.mark.asyncio
async def test_middleware_defaults_invalid_to_web():
    captured: dict = {}

    async def call_next(request):
        captured["client_type"] = request.state.client_type
        from starlette.responses import Response
        return Response("ok")

    mw = ClientMetaMiddleware(app=None)
    req = _make_request({"X-Client-Type": "rogue-os"})
    await mw.dispatch(req, call_next)
    assert captured["client_type"] == "web"


@pytest.mark.asyncio
async def test_middleware_defaults_missing_to_web():
    captured: dict = {}

    async def call_next(request):
        captured["client_type"] = request.state.client_type
        captured["client_version"] = request.state.client_version
        from starlette.responses import Response
        return Response("ok")

    mw = ClientMetaMiddleware(app=None)
    req = _make_request({})
    await mw.dispatch(req, call_next)
    assert captured["client_type"] == "web"
    assert captured["client_version"] is None


@pytest.mark.asyncio
async def test_middleware_does_not_break_existing_endpoint(
    async_client: AsyncClient
):
    """smoke test：middleware 注册后，现有 /openapi.json 仍能正常返回。"""
    res = await async_client.get(
        "/openapi.json",
        headers={"X-Client-Type": "desktop", "X-Client-Version": "0.1.0"},
    )
    assert res.status_code == 200
    assert res.headers.get("content-type", "").startswith("application/json")


def test_valid_client_types_set_complete():
    """守住 4 个合法 client_type，避免有人乱加。"""
    assert VALID_CLIENT_TYPES == {"web", "desktop", "android", "ios"}
