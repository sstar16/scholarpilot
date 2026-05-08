"""ContextVar carrying per-request BYOK override.

Set by ClientLLMOverrideMiddleware at request entry; read by LLMProviderManager.
generate_full inside the manager hot-path. asyncio Tasks inherit context, so
this propagates from middleware → handler → manager call without explicit
parameter passing.

Celery worker processes do NOT inherit (different process), so they always
see None → fall back to global active_provider, matching the design intent
that search/worker LLM calls use the platform's globally-configured provider.
"""
from contextvars import ContextVar
from typing import Optional, Dict, Any

llm_override_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "llm_override", default=None,
)
