"""LDR-inspired 新 fetcher 测试（2026-05-08）

每个新源 1 个 happy-path mock + 必要时 1 个 disabled-without-key fallback。
mock 走 monkeypatch 替换 `httpx.AsyncClient.get/post`，避免真网请求。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 共享辅助 ────────────────────────────────────────────────────────────────


class _FakeResponse:
    """伪造 httpx.Response（只暴露 fetcher 用到的 attr）。"""

    def __init__(self, status_code: int = 200, json_data: Optional[Any] = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")
        self.headers: Dict[str, str] = {}

    def json(self) -> Any:
        return self._json


def _patch_client_get(monkeypatch, fetcher_module: str, response: _FakeResponse):
    """把目标 fetcher 模块用到的 httpx client.get 替换为 mock。"""
    async def _fake_get(self, url, **kwargs):  # noqa: ARG001
        return response

    monkeypatch.setattr("httpx.AsyncClient.get", _fake_get, raising=True)


def _patch_client_post(monkeypatch, response: _FakeResponse):
    async def _fake_post(self, url, **kwargs):  # noqa: ARG001
        return response

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post, raising=True)


# ─── Wikipedia ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wikipedia_happy_path(monkeypatch):
    from app.services.fetchers.wikipedia import WikipediaFetcher

    # 维基的两段调用（list=search 然后 prop=extracts）一起 mock 同一 fake
    # 取巧：把第一个返回 search 结果，第二个返回 pages — 顺序很关键
    responses = [
        _FakeResponse(200, {
            "query": {"search": [
                {"pageid": 1, "title": "Quantum computing", "snippet": "<span class=\"searchmatch\">Quantum</span> computing is..."},
                {"pageid": 2, "title": "Quantum entanglement", "snippet": "Entanglement..."},
            ]}
        }),
        _FakeResponse(200, {
            "query": {"pages": {
                "1": {"extract": "Quantum computing is a type of computation..."},
                "2": {"extract": "Quantum entanglement is a phenomenon..."},
            }}
        }),
    ]
    call_idx = {"i": 0}

    async def _seq_get(self, url, **kwargs):  # noqa: ARG001
        i = call_idx["i"]
        call_idx["i"] += 1
        return responses[min(i, len(responses) - 1)]

    monkeypatch.setattr("httpx.AsyncClient.get", _seq_get, raising=True)

    f = WikipediaFetcher()
    docs = await f.fetch("quantum computing", max_results=10)
    assert len(docs) == 2
    assert docs[0]["source"] == "wikipedia"
    assert docs[0]["doc_type"] == "encyclopedia"
    assert "Quantum computing" in docs[0]["title"]
    assert docs[0]["abstract"]
    assert docs[0]["url"].startswith("https://en.wikipedia.org/wiki/")


@pytest.mark.asyncio
async def test_wikipedia_zh_endpoint_switches(monkeypatch):
    from app.services.fetchers.wikipedia import WikipediaFetcher, _wikipedia_endpoint

    assert _wikipedia_endpoint("zh") == "https://zh.wikipedia.org/w/api.php"
    assert _wikipedia_endpoint("en") == "https://en.wikipedia.org/w/api.php"
    assert _wikipedia_endpoint(None) == "https://en.wikipedia.org/w/api.php"


# ─── Tavily ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tavily_happy_path(monkeypatch):
    from app.services.fetchers.tavily import TavilyFetcher

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _patch_client_post(monkeypatch, _FakeResponse(200, {
        "results": [
            {"title": "Article 1", "url": "https://example.com/1", "content": "Body 1", "score": 0.9},
            {"title": "Article 2", "url": "https://example.com/2", "content": "Body 2", "score": 0.7},
        ]
    }))

    f = TavilyFetcher()
    docs = await f.fetch("ai research", max_results=10)
    assert len(docs) == 2
    assert docs[0]["source"] == "tavily"
    assert docs[0]["doc_type"] == "web_page"
    assert docs[0]["url"] == "https://example.com/1"
    assert docs[0]["abstract"] == "Body 1"


@pytest.mark.asyncio
async def test_tavily_no_key_returns_empty(monkeypatch):
    from app.services.fetchers.tavily import TavilyFetcher

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    f = TavilyFetcher()
    docs = await f.fetch("ai research", max_results=10)
    assert docs == []


# ─── Zenodo ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zenodo_happy_path(monkeypatch):
    from app.services.fetchers.zenodo import ZenodoFetcher

    _patch_client_get(monkeypatch, "zenodo", _FakeResponse(200, {
        "hits": {"hits": [
            {
                "id": 12345,
                "metadata": {
                    "title": "COVID-19 Genome Dataset",
                    "creators": [{"name": "Doe, Jane"}, {"name": "Smith, Bob"}],
                    "description": "<p>A curated <b>dataset</b> of...</p>",
                    "doi": "10.5281/zenodo.12345",
                    "publication_date": "2024-03-15",
                    "resource_type": {"type": "dataset"},
                    "keywords": ["covid", "genome"],
                    "license": {"id": "cc-by-4.0"},
                },
                "links": {"self_html": "https://zenodo.org/record/12345"},
            },
        ]}
    }))

    f = ZenodoFetcher()
    docs = await f.fetch("covid genome", max_results=10)
    assert len(docs) == 1
    d = docs[0]
    assert d["source"] == "zenodo"
    assert d["doc_type"] == "dataset"
    assert d["title"] == "COVID-19 Genome Dataset"
    assert "Doe, Jane" in d["authors"]
    assert d["doi"] == "10.5281/zenodo.12345"
    assert "<p>" not in (d["abstract"] or "")  # HTML 已剥
    assert d["metadata"]["resource_type"] == "dataset"


# ─── DuckDuckGo ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duckduckgo_no_lib_returns_empty(monkeypatch):
    """duckduckgo-search 库未装时该源 fallback 返回 []。"""
    import sys

    from app.services.fetchers.duckduckgo import DuckDuckGoFetcher

    # 强行让 import 失败（用 sys.modules 替换）
    monkeypatch.setitem(sys.modules, "duckduckgo_search", None)

    f = DuckDuckGoFetcher()
    docs = await f.fetch("ai research", max_results=10)
    assert docs == []


@pytest.mark.asyncio
async def test_duckduckgo_with_mock_lib(monkeypatch):
    """模拟 duckduckgo-search 库已装的场景。"""
    import sys
    import types

    fake_module = types.ModuleType("duckduckgo_search")

    class _FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, **kwargs):  # noqa: ARG002
            return [
                {"title": "Result 1", "href": "https://example.com/1", "body": "snippet 1"},
                {"title": "Result 2", "href": "https://example.com/2", "body": "snippet 2"},
            ]

    fake_module.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "duckduckgo_search", fake_module)

    from app.services.fetchers.duckduckgo import DuckDuckGoFetcher
    f = DuckDuckGoFetcher()
    docs = await f.fetch("ai research", max_results=10)
    assert len(docs) == 2
    assert docs[0]["source"] == "duckduckgo"
    assert docs[0]["url"] == "https://example.com/1"


# ─── GitHub ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_github_happy_path(monkeypatch):
    from app.services.fetchers.github_search import GitHubFetcher

    _patch_client_get(monkeypatch, "github", _FakeResponse(200, {
        "items": [
            {
                "id": 999,
                "full_name": "facebook/react",
                "description": "A JavaScript library",
                "stargazers_count": 200000,
                "forks_count": 40000,
                "language": "JavaScript",
                "topics": ["javascript", "ui"],
                "created_at": "2013-05-24T16:15:54Z",
                "pushed_at": "2025-12-01T10:00:00Z",
                "owner": {"login": "facebook"},
                "html_url": "https://github.com/facebook/react",
            },
        ]
    }))

    f = GitHubFetcher()
    docs = await f.fetch("react ui", max_results=5)
    assert len(docs) == 1
    d = docs[0]
    assert d["source"] == "github"
    assert d["doc_type"] == "code_repo"
    assert d["title"] == "facebook/react"
    assert d["citation_count"] == 200000  # stars 当 citation
    assert d["metadata"]["language"] == "JavaScript"


@pytest.mark.asyncio
async def test_github_no_token_still_works(monkeypatch):
    """没 GITHUB_TOKEN 也能跑（只是 60/h 限额）。"""
    from app.services.fetchers.github_search import GitHubFetcher

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _patch_client_get(monkeypatch, "github", _FakeResponse(200, {"items": []}))
    f = GitHubFetcher()
    docs = await f.fetch("anything", max_results=5)
    assert docs == []  # mock 返回空 items，仍正常返回 [] 不抛异常


# ─── Stack Exchange ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stackexchange_happy_path(monkeypatch):
    from app.services.fetchers.stackexchange import StackExchangeFetcher

    _patch_client_get(monkeypatch, "stackexchange", _FakeResponse(200, {
        "items": [
            {
                "question_id": 42,
                "title": "How to async/await in Python?",
                "body": "<p>I want to use <code>async</code></p>",
                "score": 150,
                "answer_count": 5,
                "is_answered": True,
                "tags": ["python", "asyncio"],
                "creation_date": 1700000000,
                "last_activity_date": 1701000000,
                "owner": {"display_name": "user1"},
                "link": "https://stackoverflow.com/questions/42",
            },
        ]
    }))

    f = StackExchangeFetcher()
    docs = await f.fetch("python async", max_results=5)
    assert len(docs) == 1
    d = docs[0]
    assert d["source"] == "stackexchange"
    assert d["doc_type"] == "qa"
    assert d["citation_count"] == 150  # score 当 citation
    assert d["metadata"]["is_answered"] is True
    assert "<p>" not in (d["abstract"] or "")


# ─── Registry / 元数据完备性 ─────────────────────────────────────────────────


def test_new_sources_registered():
    """6 个新 fetcher 都在 ALL_FETCHERS 和 SourceId 里。"""
    from app.services.fetchers.international import ALL_FETCHERS
    from app.services.fetchers.types import ALL_SOURCE_IDS

    new_sources = {"wikipedia", "tavily", "zenodo", "duckduckgo", "github", "stackexchange"}
    assert new_sources <= set(ALL_FETCHERS.keys()), "ALL_FETCHERS 缺新源"
    assert new_sources <= ALL_SOURCE_IDS, "SourceId Literal 缺新源"


def test_new_sources_metadata():
    """6 个新源在 FetcherRegistry.SOURCES 都有 metadata。"""
    from app.services.fetchers.base import FetcherRegistry

    info = {e["id"]: e for e in FetcherRegistry.get_all_info()}
    for sid in ("wikipedia", "tavily", "zenodo", "duckduckgo", "github", "stackexchange"):
        assert sid in info, f"FetcherRegistry 缺 {sid} 元数据"
        e = info[sid]
        assert e["name"] and e["description"]
        assert e["doc_type"] in {"encyclopedia", "web_page", "dataset", "code_repo", "qa"}
