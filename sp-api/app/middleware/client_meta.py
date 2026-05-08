"""ClientMetaMiddleware — sp-api 增强版（含 MIN_CLIENT_VERSION 拦截）。

vs backend/app/middleware/client_meta.py 加：
- 解析 X-Client-Version 后，desktop 客户端 < settings.min_client_version 返 426 Upgrade Required
- web/未知客户端不拦截（兼容 Swagger / curl 调试）

强升机制：客户端启动时调 GET /health，如果返 426 强制弹升级提示。
"""
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


VALID_CLIENT_TYPES = {"web", "desktop", "android", "ios"}

# 路径白名单 — 老客户端也能拿到 health/upgrade 提示，否则 stuck on 426 with no UI
_BYPASS_PATHS = {"/", "/health", "/api/health", "/docs", "/openapi.json", "/redoc"}


def _parse_version(v: Optional[str]) -> Optional[tuple[int, int, int]]:
    """解析 'X.Y.Z' → (X, Y, Z)；非 semver 或 None 返 None。"""
    if not v:
        return None
    parts = v.strip().split(".")
    if len(parts) < 2:
        return None
    out = []
    for p in parts[:3]:
        # 允许 '0.2.0-beta' 这种 — 取数字前缀
        digits = ""
        for ch in p:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return None
        out.append(int(digits))
    while len(out) < 3:
        out.append(0)
    return (out[0], out[1], out[2])


class ClientMetaMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_type = request.headers.get("X-Client-Type", "web")
        if client_type not in VALID_CLIENT_TYPES:
            client_type = "web"
        client_version = request.headers.get("X-Client-Version")
        request.state.client_type = client_type
        request.state.client_version = client_version

        # 仅对 desktop 客户端做版本拦截；web 不拦
        if client_type == "desktop" and request.url.path not in _BYPASS_PATHS:
            from app.config import settings
            min_v = _parse_version(settings.min_client_version)
            cur_v = _parse_version(client_version)
            if min_v is not None and (cur_v is None or cur_v < min_v):
                return JSONResponse(
                    status_code=426,
                    content={
                        "code": "client_upgrade_required",
                        "message": (
                            f"客户端版本 {client_version or '(unknown)'} 过旧，"
                            f"最低要求 {settings.min_client_version}，请升级"
                        ),
                        "min_client_version": settings.min_client_version,
                    },
                    headers={"Upgrade": "ScholarPilot-Desktop"},
                )

        return await call_next(request)
