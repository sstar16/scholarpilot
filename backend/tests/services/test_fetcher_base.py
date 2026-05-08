"""Tests for AbstractFetcher: shared-client caching + typed-retry policy.

Inspired by curl's connection pool philosophy and retry discipline. The
goals here are concrete:
1) Default ``_http_client()`` returns the same AsyncClient across calls,
   so httpx's connection pool actually carries over and TLS handshakes
   are amortised.
2) ``safe_fetch`` distinguishes network-transient errors (retry) from
   non-retryable HTTP 4xx (give up immediately) and from internal bugs
   (give up + ERROR log).
"""
from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

# Stub source_config_store so we don't pull redis at import time.
_scs = types.ModuleType("app.services.source_config_store")
_scs.get_proxy_for_source = lambda _sid: None
sys.modules.setdefault("app.services.source_config_store", _scs)

from app.services.fetchers.base import (  # noqa: E402
    AbstractFetcher,
    _RETRYABLE_HTTP_STATUSES,
    _RETRYABLE_NETWORK_ERRORS,
)


class _StubFetcher(AbstractFetcher):
    """Minimal concrete fetcher whose ``fetch`` is a list of canned outcomes
    (each tick yields the next item: a list of docs OR an exception to raise)."""

    source_id = "stub"

    def __init__(self) -> None:
        self.script: list[Any] = []
        self.fetch_calls = 0

    async def fetch(self, *_args, **_kwargs):
        self.fetch_calls += 1
        if not self.script:
            return []
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Don't actually sleep between retries — keeps tests <1s."""
    import asyncio as _aio
    monkeypatch.setattr(_aio, "sleep", AsyncMock(return_value=None))


# ── Shared-client caching ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shared_client_reused_across_calls():
    f = _StubFetcher()
    async with f._http_client() as c1:
        pass
    async with f._http_client() as c2:
        pass
    assert c1 is c2, "default _http_client() must return the same instance"
    assert not c1.is_closed
    await f.aclose()
    assert c1.is_closed


@pytest.mark.asyncio
async def test_shared_client_recreated_after_close():
    f = _StubFetcher()
    async with f._http_client() as c1:
        pass
    await c1.aclose()
    async with f._http_client() as c2:
        pass
    assert c1 is not c2, "after close, next call must build fresh client"


@pytest.mark.asyncio
async def test_oneshot_client_when_kwargs_given():
    """Passing kwargs → fresh client per call (legacy behaviour)."""
    f = _StubFetcher()
    async with f._http_client(headers={"X": "1"}) as c1:
        pass
    async with f._http_client(headers={"X": "2"}) as c2:
        pass
    assert c1 is not c2
    assert c1.is_closed
    assert c2.is_closed


@pytest.mark.asyncio
async def test_oneshot_does_not_pollute_shared_cache():
    f = _StubFetcher()
    async with f._http_client(headers={"X": "1"}) as one_shot:
        pass
    async with f._http_client() as shared:
        pass
    assert one_shot is not shared, "one-shot must not be cached"
    assert shared is not None
    await f.aclose()


@pytest.mark.asyncio
async def test_aclose_safe_when_no_client_built():
    f = _StubFetcher()
    await f.aclose()  # must not raise


@pytest.mark.asyncio
async def test_two_fetchers_have_separate_caches():
    a = _StubFetcher()
    b = _StubFetcher()
    async with a._http_client() as ca:
        pass
    async with b._http_client() as cb:
        pass
    assert ca is not cb
    await a.aclose()
    await b.aclose()


# ── Typed-retry policy ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_first_try():
    f = _StubFetcher()
    f.script = [[{"title": "ok"}]]
    sid, data = await f.safe_fetch("q")
    assert sid == "stub"
    assert data == [{"title": "ok"}]
    assert f.fetch_calls == 1


@pytest.mark.asyncio
async def test_network_error_retries_then_succeeds():
    f = _StubFetcher()
    f.script = [
        httpx.ConnectError("conn refused"),
        [{"title": "recovered"}],
    ]
    sid, data = await f.safe_fetch("q")
    assert data == [{"title": "recovered"}]
    assert f.fetch_calls == 2


@pytest.mark.asyncio
async def test_network_error_exhausts_retries():
    f = _StubFetcher()
    f.script = [
        httpx.ConnectError("1"),
        httpx.ConnectError("2"),
        httpx.ConnectError("3"),
    ]
    sid, data = await f.safe_fetch("q")
    assert data == []
    assert f.fetch_calls == 3, "should retry RETRY_COUNT (=2) + initial = 3 times"


@pytest.mark.asyncio
async def test_timeout_is_retryable():
    f = _StubFetcher()
    import asyncio as _aio
    f.script = [_aio.TimeoutError("slow"), [{"title": "ok"}]]
    sid, data = await f.safe_fetch("q")
    assert data == [{"title": "ok"}]


@pytest.mark.asyncio
async def test_http_4xx_does_not_retry():
    """A 401/403/404 should fail FAST — no point hammering the same dead URL."""
    f = _StubFetcher()
    response = MagicMock()
    response.status_code = 401
    f.script = [
        httpx.HTTPStatusError("auth", request=MagicMock(), response=response),
    ]
    sid, data = await f.safe_fetch("q")
    assert data == []
    assert f.fetch_calls == 1, "4xx must not be retried"


@pytest.mark.asyncio
async def test_http_429_is_retryable():
    """Rate-limited responses should back off and retry."""
    f = _StubFetcher()
    response = MagicMock()
    response.status_code = 429
    f.script = [
        httpx.HTTPStatusError("rate", request=MagicMock(), response=response),
        [{"title": "ok"}],
    ]
    sid, data = await f.safe_fetch("q")
    assert data == [{"title": "ok"}]
    assert f.fetch_calls == 2


@pytest.mark.asyncio
async def test_http_503_is_retryable():
    f = _StubFetcher()
    response = MagicMock()
    response.status_code = 503
    f.script = [
        httpx.HTTPStatusError("overload", request=MagicMock(), response=response),
        [{"title": "ok"}],
    ]
    sid, data = await f.safe_fetch("q")
    assert data == [{"title": "ok"}]


@pytest.mark.asyncio
async def test_unknown_exception_does_not_retry():
    """A ValueError from inside fetch() likely means a parser bug —
    retrying it just wastes time."""
    f = _StubFetcher()
    f.script = [ValueError("bad json"), [{"title": "would-have-recovered"}]]
    sid, data = await f.safe_fetch("q")
    assert data == []
    assert f.fetch_calls == 1


def test_retry_constants_sane():
    # Sanity: every retryable network error type is a real httpx class
    assert all(isinstance(t, type) for t in _RETRYABLE_NETWORK_ERRORS)
    # 429 + 5xx (NOT 500 itself by design — 500 is server bug, not transient)
    assert 429 in _RETRYABLE_HTTP_STATUSES
    assert 503 in _RETRYABLE_HTTP_STATUSES
    assert 504 in _RETRYABLE_HTTP_STATUSES
    assert 500 not in _RETRYABLE_HTTP_STATUSES  # ambiguous — fetcher decides
    assert 401 not in _RETRYABLE_HTTP_STATUSES
    assert 404 not in _RETRYABLE_HTTP_STATUSES
