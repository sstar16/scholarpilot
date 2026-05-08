"""
JSON mode / response_format 端到端单测。

验证维度：
1. cache key 对 None / json_object 生成不同 hash（避免跨模式串缓存）
2. OpenAICompatibleProvider 把 response_format 放进 body，且 prompt 不含 "json" 时自动追加兜底句
3. OllamaProvider 把 response_format 转为顶层 `"format": "json"`
4. AnthropicProvider 没有原生支持，在 prompt 不含 "json" 时追加兜底句
5. LLMProviderManager.generate_full 把 response_format 透传给 provider

不依赖 DB / Redis / 外部 LLM；httpx 全部 monkeypatch。
"""
from __future__ import annotations

import json as json_mod
from typing import Any, Dict, List, Optional

import httpx
import pytest


# ── Fake httpx.AsyncClient ──────────────────────────────────────────────

class _CapturedRequest:
    def __init__(self) -> None:
        self.url: Optional[str] = None
        self.json_body: Optional[Dict[str, Any]] = None
        self.headers: Optional[Dict[str, str]] = None


class _FakeResponse:
    def __init__(self, status_code: int, data: Dict[str, Any]) -> None:
        self.status_code = status_code
        self._data = data
        self.text = json_mod.dumps(data)

    def json(self) -> Dict[str, Any]:
        return self._data


def _make_fake_client(
    captured: List[_CapturedRequest], response_data: Dict[str, Any]
):
    """Return a class that mimics httpx.AsyncClient, recording POST bodies."""

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._captured = _CapturedRequest()
            captured.append(self._captured)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(
            self, url: str, headers: Optional[Dict[str, str]] = None,
            json: Optional[Dict[str, Any]] = None,
        ) -> _FakeResponse:
            self._captured.url = url
            self._captured.headers = headers
            self._captured.json_body = json
            return _FakeResponse(200, response_data)

    return _FakeAsyncClient


# ── 1. cache key ────────────────────────────────────────────────────────

class TestCacheKeyResponseFormat:
    def test_key_changes_with_response_format(self):
        from app.services.core.llm_cache import _make_key
        k_text = _make_key("same prompt", 0.1, "deepseek", "deepseek-chat")
        k_json = _make_key(
            "same prompt", 0.1, "deepseek", "deepseek-chat",
            response_format={"type": "json_object"},
        )
        assert k_text != k_json, "JSON mode 和 text mode 必须分桶，否则会串缓存"

    def test_same_format_same_key(self):
        from app.services.core.llm_cache import _make_key
        k1 = _make_key(
            "p", 0.1, "deepseek", "deepseek-chat",
            response_format={"type": "json_object"},
        )
        k2 = _make_key(
            "p", 0.1, "deepseek", "deepseek-chat",
            response_format={"type": "json_object"},
        )
        assert k1 == k2


# ── 2. OpenAI / DeepSeek / Moonshot ────────────────────────────────────

class TestOpenAICompatibleJsonMode:
    OPENAI_RESP = {
        "choices": [{
            "message": {"content": "{\"ok\": true}"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    @pytest.mark.asyncio
    async def test_response_format_in_body(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.OPENAI_RESP),
        )

        provider = llm_providers.OpenAICompatibleProvider({
            "api_key": "fake",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "provider_name": "deepseek",
        })

        result = await provider.generate_full(
            "please return json as an object",
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        assert result is not None
        assert len(captured) == 1
        body = captured[0].json_body
        assert body is not None
        assert body.get("response_format") == {"type": "json_object"}
        # prompt 里含 "json"，不应被 append 兜底
        assert body["messages"][0]["content"] == "please return json as an object"

    @pytest.mark.asyncio
    async def test_json_hint_auto_appended_when_missing(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.OPENAI_RESP),
        )

        provider = llm_providers.OpenAICompatibleProvider({
            "api_key": "fake",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "provider_name": "deepseek",
        })
        # prompt 完全没有 "json" 字样
        await provider.generate_full(
            "Hello world, no magic keyword here",
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        body = captured[0].json_body
        assert "Response must be valid JSON" in body["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_no_response_format_no_change(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.OPENAI_RESP),
        )

        provider = llm_providers.OpenAICompatibleProvider({
            "api_key": "fake",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "provider_name": "deepseek",
        })
        await provider.generate_full("Hello", temperature=0.1)
        body = captured[0].json_body
        assert "response_format" not in body
        assert body["messages"][0]["content"] == "Hello"


# ── 3. Ollama ──────────────────────────────────────────────────────────

class TestOllamaJsonMode:
    OLLAMA_RESP = {
        "response": "{\"ok\": true}",
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 5,
    }

    @pytest.mark.asyncio
    async def test_format_json_at_top_level(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.OLLAMA_RESP),
        )

        provider = llm_providers.OllamaProvider({
            "host": "http://fake:11434",
            "model": "llama3.2",
        })
        await provider.generate_full(
            "ping",
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        body = captured[0].json_body
        # Ollama 用顶层 "format" 字段，不是 response_format
        assert body.get("format") == "json"
        assert "response_format" not in body

    @pytest.mark.asyncio
    async def test_no_format_without_response_format(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.OLLAMA_RESP),
        )

        provider = llm_providers.OllamaProvider({
            "host": "http://fake:11434",
            "model": "llama3.2",
        })
        await provider.generate_full("ping", temperature=0.1)
        body = captured[0].json_body
        assert "format" not in body


# ── 4. Anthropic ───────────────────────────────────────────────────────

class TestAnthropicJsonMode:
    ANTHROPIC_RESP = {
        "content": [{"type": "text", "text": "{\"ok\": true}"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    @pytest.mark.asyncio
    async def test_hint_appended_when_missing(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.ANTHROPIC_RESP),
        )

        provider = llm_providers.AnthropicProvider({
            "api_key": "fake",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-4-20250514",
        })
        await provider.generate_full(
            "no magic keyword",
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        body = captured[0].json_body
        content = body["messages"][0]["content"]
        assert "Response must be valid JSON" in content
        # Anthropic 不支持 OpenAI 风格的 response_format 字段，不应出现在 body 里
        assert "response_format" not in body

    @pytest.mark.asyncio
    async def test_no_change_when_prompt_has_json(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.ANTHROPIC_RESP),
        )

        provider = llm_providers.AnthropicProvider({
            "api_key": "fake",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-4-20250514",
        })
        await provider.generate_full(
            "return a JSON blob please",
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        body = captured[0].json_body
        assert body["messages"][0]["content"] == "return a JSON blob please"


# ── 5. Manager 透传 ─────────────────────────────────────────────────────

class TestManagerPassThrough:
    @pytest.mark.asyncio
    async def test_generate_passes_response_format_to_provider(self, monkeypatch):
        from app.services.core import llm_providers

        # 禁用 cache，避免命中缓存绕过 provider
        monkeypatch.setattr(
            "app.services.core.llm_cache.should_cache", lambda temp: False,
        )

        captured_kwargs: Dict[str, Any] = {}

        class _SpyProvider(llm_providers.BaseLLMProvider):
            def __init__(self) -> None:
                super().__init__({})
                self.model = "spy-model"

            @property
            def provider_name(self) -> str:
                return "spy"

            async def generate_full(
                self, prompt, temperature=0.1, max_tokens=None,
                response_format=None, frequency_penalty=None,
            ):
                captured_kwargs["response_format"] = response_format
                captured_kwargs["frequency_penalty"] = frequency_penalty
                captured_kwargs["prompt"] = prompt
                return llm_providers.LLMResult(
                    text="{\"ok\": true}",
                    usage=llm_providers.LLMUsage(input_tokens=1, output_tokens=1),
                    cost_usd=0.0,
                    latency_ms=1,
                    provider="spy",
                    model="spy-model",
                )

            async def generate_stream(self, prompt, temperature=0.1):  # type: ignore
                if False:
                    yield  # pragma: no cover

            async def check_connection(self):
                return {"connected": True}

        mgr = llm_providers.LLMProviderManager()
        mgr.providers["spy"] = _SpyProvider()
        mgr.active_provider_id = "spy"

        text = await mgr.generate(
            "hello world json output",
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        assert text == "{\"ok\": true}"
        assert captured_kwargs["response_format"] == {"type": "json_object"}


# ── 6. frequency_penalty 透传 ───────────────────────────────────────────

class TestFrequencyPenalty:
    OPENAI_RESP = {
        "choices": [{
            "message": {"content": "hi"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }

    @pytest.mark.asyncio
    async def test_frequency_penalty_in_openai_body(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.OPENAI_RESP),
        )

        provider = llm_providers.OpenAICompatibleProvider({
            "api_key": "fake",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "provider_name": "deepseek",
        })
        await provider.generate_full("hello", frequency_penalty=0.5)
        body = captured[0].json_body
        assert body.get("frequency_penalty") == 0.5

    @pytest.mark.asyncio
    async def test_no_frequency_penalty_absent_from_body(self, monkeypatch):
        from app.services.core import llm_providers

        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, self.OPENAI_RESP),
        )

        provider = llm_providers.OpenAICompatibleProvider({
            "api_key": "fake",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "provider_name": "deepseek",
        })
        await provider.generate_full("hello")
        body = captured[0].json_body
        # 默认 None 时不出现在 body 里，保持 API 默认值
        assert "frequency_penalty" not in body


# ── 7. reasoning_content 解析（deepseek-reasoner）──────────────────────

class TestReasoningContent:
    @pytest.mark.asyncio
    async def test_reasoning_populated_when_present(self, monkeypatch):
        from app.services.core import llm_providers

        resp = {
            "choices": [{
                "message": {
                    "content": "最终回答",
                    "reasoning_content": "让我一步步思考：首先... 其次...",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, resp),
        )

        provider = llm_providers.OpenAICompatibleProvider({
            "api_key": "fake",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-reasoner",
            "provider_name": "deepseek",
        })
        result = await provider.generate_full("question")
        assert result is not None
        assert result.text == "最终回答"
        assert result.reasoning == "让我一步步思考：首先... 其次..."

    @pytest.mark.asyncio
    async def test_reasoning_none_for_non_reasoning_model(self, monkeypatch):
        from app.services.core import llm_providers

        resp = {
            "choices": [{
                "message": {"content": "answer"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        captured: List[_CapturedRequest] = []
        monkeypatch.setattr(
            llm_providers.httpx, "AsyncClient",
            _make_fake_client(captured, resp),
        )

        provider = llm_providers.OpenAICompatibleProvider({
            "api_key": "fake",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "provider_name": "deepseek",
        })
        result = await provider.generate_full("q")
        assert result is not None
        assert result.reasoning is None
