"""Middleware: parse X-User-LLM-* headers into request.state.user_llm_override.

Used by `app.services.core.llm_request_resolver.get_llm_for_request` to optionally
construct a per-request LLM provider with the user's BYOK API key.

Security:
- Header values (api_key) MUST NEVER be logged. Logging middleware further down
  the chain (`request_logger.py`) already redacts headers matching `*-Key` /
  `Authorization`, but this middleware also avoids any logger.info() call that
  would mention the key.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.core.llm_request_context import llm_override_var

VALID_PROVIDERS = {"openai", "anthropic", "deepseek", "moonshot", "custom"}


class ClientLLMOverrideMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        provider = request.headers.get("X-User-LLM-Provider")
        api_key = request.headers.get("X-User-LLM-Key")
        override = None
        # 最小完整集：provider + key；少一个则丢弃整组
        if provider and api_key and provider in VALID_PROVIDERS:
            override = {
                "provider": provider,
                "api_key": api_key,
                "model": request.headers.get("X-User-LLM-Model"),
                "base_url": request.headers.get("X-User-LLM-Base-Url"),
            }
        request.state.user_llm_override = override
        # M3: 同时 set contextvar，让 LLMProviderManager.generate_full 在调用栈深处也能读到
        token = llm_override_var.set(override)
        try:
            response: Response = await call_next(request)
        finally:
            llm_override_var.reset(token)
        return response
