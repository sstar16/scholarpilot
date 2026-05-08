"""
FastAPI HTTP request/response logging middleware for DevTools.
"""
import re
import time
import traceback
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/"}
SKIP_PREFIXES = ("/api/devtools/",)
POLLING_SUFFIXES = ("/status",)

_UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE)


def _normalize_path(path: str) -> str:
    return _UUID_RE.sub(':id', path)


def _should_skip(path: str) -> bool:
    if path in SKIP_PATHS or path.startswith("/docs"):
        return True
    return any(path.startswith(p) for p in SKIP_PREFIXES)


def _is_polling(path: str) -> bool:
    return any(path.endswith(s) for s in POLLING_SUFFIXES)


def _record_log(method: str, path: str, status_code: int, duration_ms: int, error_trace: str | None, query: str | None):
    """Write log entry to DevTools buffer. Never raises."""
    try:
        from app.services.devtools.log_writer import log_buffer
        norm_path = _normalize_path(path)
        level = "ERROR" if status_code >= 500 or error_trace else (
            "WARN" if status_code >= 400 else "INFO"
        )
        log_buffer.add({
            "level": level,
            "source": "http",
            "category": f"{method} {norm_path}",
            "message": f"{method} {norm_path} → {status_code} ({duration_ms}ms)",
            "context": {
                "method": method,
                "path": path,
                "normalized": norm_path,
                "status_code": status_code,
                "query": query,
            },
            "duration_ms": duration_ms,
            "error_trace": error_trace,
        })
    except Exception:
        pass


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if _should_skip(path):
            return await call_next(request)

        method = request.method
        start = time.time()
        query = str(request.query_params) if request.query_params else None
        polling = _is_polling(path)

        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = int((time.time() - start) * 1000)
            _record_log(method, path, 500, duration_ms, traceback.format_exc(), query)
            raise

        duration_ms = int((time.time() - start) * 1000)
        # Skip logging for normal polling responses
        if not (polling and response.status_code < 500):
            _record_log(method, path, response.status_code, duration_ms, None, query)

        return response
