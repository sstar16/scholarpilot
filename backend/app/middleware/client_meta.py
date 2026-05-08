"""ClientMetaMiddleware：解析 X-Client-Type / X-Client-Version 头到 request.state，
方便下游路由（推送注册、计费埋点等）按客户端区分行为。

未声明或非法值默认归为 'web'。
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


VALID_CLIENT_TYPES = {"web", "desktop", "android", "ios"}


class ClientMetaMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_type = request.headers.get("X-Client-Type", "web")
        if client_type not in VALID_CLIENT_TYPES:
            client_type = "web"
        request.state.client_type = client_type
        request.state.client_version = request.headers.get("X-Client-Version")
        return await call_next(request)
