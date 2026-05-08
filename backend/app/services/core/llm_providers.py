#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多LLM提供商抽象层
支持：本地Ollama、OpenAI API、Anthropic Claude API、DeepSeek API、自定义API端点
用户可自行配置API密钥和模型选择
"""

import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, AsyncIterator
import logging
import httpx

from app.services.core.llm_types import (
    LLMResult, LLMChunk, LLMUsage,
    compute_cost, estimate_tokens,
)
from app.services.core.llm_context import get_llm_context
# HookEngine import is lazy inside the methods to avoid startup circular

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """LLM提供商基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # 单次 LLM HTTP 调用最长 25s — 比上层 asyncio.wait_for(30s) 略短，
        # 确保 timeout 一定先在 httpx 层抛出（带明确异常），不会让 asyncio 撕裂连接
        self.timeout = config.get("timeout", 25.0)

    @abstractmethod
    async def generate_full(
        self, prompt: str, temperature: float = 0.1, max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        frequency_penalty: Optional[float] = None,
    ) -> Optional[LLMResult]:
        """Full non-streaming response with usage + cost. Returns None on failure.

        response_format: e.g. {"type": "json_object"} to enforce structured JSON output.
        frequency_penalty: -2.0 ~ 2.0 for OpenAI-compat families (降低重复)。
        Providers that don't support these flags should ignore them gracefully.
        """

    @abstractmethod
    async def generate_stream(
        self, prompt: str, temperature: float = 0.1
    ) -> AsyncIterator[LLMChunk]:
        """Token-by-token streaming. Final chunk has done=True with usage + cost."""

    async def generate(
        self, prompt: str, temperature: float = 0.1,
        response_format: Optional[Dict[str, Any]] = None,
        frequency_penalty: Optional[float] = None,
    ) -> Optional[str]:
        """Backward-compat wrapper: returns text or None."""
        result = await self.generate_full(
            prompt, temperature,
            response_format=response_format,
            frequency_penalty=frequency_penalty,
        )
        return result.text if result else None

    @abstractmethod
    async def check_connection(self) -> Dict[str, Any]:
        """检查连接状态"""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass


class OllamaProvider(BaseLLMProvider):
    """本地Ollama提供商"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.host = config.get("host", "http://localhost:11434")
        self.model = config.get("model", "llama3.2")

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def generate_full(
        self, prompt: str, temperature: float = 0.1, max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        frequency_penalty: Optional[float] = None,
    ) -> Optional[LLMResult]:
        # Ollama 的 repeat_penalty 语义和 OpenAI frequency_penalty 不同（1~2 vs -2~2），
        # 不做映射以免误导；参数接收但 no-op。
        _ = frequency_penalty
        start = time.monotonic()
        # Ollama 用顶层 "format": "json" 启用 JSON mode（不是 response_format）
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 500,
            },
        }
        if response_format and response_format.get("type") == "json_object":
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=None) as client:
                response = await client.post(
                    f"{self.host}/api/generate",
                    json=payload,
                )
                if response.status_code == 200:
                    data = response.json()
                    text = data.get("response", "")
                    # Ollama returns prompt_eval_count and eval_count in JSON
                    usage = LLMUsage(
                        input_tokens=data.get("prompt_eval_count") or estimate_tokens(prompt),
                        output_tokens=data.get("eval_count") or estimate_tokens(text),
                    )
                    return LLMResult(
                        text=text,
                        usage=usage,
                        cost_usd=compute_cost(self.model, usage),
                        latency_ms=int((time.monotonic() - start) * 1000),
                        provider="ollama",
                        model=self.model,
                        finish_reason=data.get("done_reason"),
                    )
        except Exception as e:
            logger.warning("[Ollama] 生成错误: %s", e)
        return None

    async def generate_stream(
        self, prompt: str, temperature: float = 0.1
    ) -> AsyncIterator[LLMChunk]:
        start = time.monotonic()
        accumulated = ""
        prompt_eval_count = 0
        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": True,
                        "options": {
                            "temperature": temperature,
                            "num_predict": 500,
                        },
                    },
                ) as response:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        delta = data.get("response", "")
                        accumulated += delta
                        if delta:
                            yield LLMChunk(
                                delta=delta,
                                provider="ollama",
                                model=self.model,
                            )
                        if data.get("done"):
                            prompt_eval_count = data.get("prompt_eval_count") or estimate_tokens(prompt)
                            usage = LLMUsage(
                                input_tokens=prompt_eval_count,
                                output_tokens=data.get("eval_count") or estimate_tokens(accumulated),
                            )
                            yield LLMChunk(
                                delta="",
                                done=True,
                                usage=usage,
                                cost_usd=compute_cost(self.model, usage),
                                latency_ms=int((time.monotonic() - start) * 1000),
                                provider="ollama",
                                model=self.model,
                                finish_reason=data.get("done_reason"),
                            )
                            return
        except Exception as e:
            logger.warning("[Ollama] 流式错误: %s", e)
            # Emit an error-done chunk with whatever we got
            yield LLMChunk(
                delta="",
                done=True,
                usage=LLMUsage(
                    input_tokens=estimate_tokens(prompt),
                    output_tokens=estimate_tokens(accumulated),
                ),
                latency_ms=int((time.monotonic() - start) * 1000),
                provider="ollama",
                model=self.model,
                finish_reason="error",
            )

    async def check_connection(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0, proxy=None) as client:
                response = await client.get(f"{self.host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {
                        "connected": True,
                        "provider": "ollama",
                        "available_models": models,
                        "current_model": self.model
                    }
        except Exception as e:
            logger.warning("[Ollama] 连接检查失败: %s", e)
        return {
            "connected": False,
            "provider": "ollama",
            "error": "无法连接到Ollama服务"
        }


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI兼容API提供商（支持OpenAI、DeepSeek、Moonshot、jiekou.ai等）"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model", "gpt-4o-mini")
        self._provider_name = config.get("provider_name", "openai")
        self.max_tokens = config.get("max_tokens", 4096)
        # DeepSeek max_tokens 上限 8192
        if "deepseek" in self.base_url.lower() and self.max_tokens > 8192:
            self.max_tokens = 8192
        # 长 prompt（带全文+KG+笔记）回答常 > 25s；给 OpenAI-compat 宽限到 120s
        if self.timeout < 120.0:
            self.timeout = 120.0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def generate_full(
        self, prompt: str, temperature: float = 0.1, max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        frequency_penalty: Optional[float] = None,
    ) -> Optional[LLMResult]:
        if not self.api_key:
            logger.warning("[%s] 未配置API密钥", self._provider_name)
            return None
        start = time.monotonic()
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        # JSON mode：OpenAI/DeepSeek/Moonshot 强制要求 prompt 里提到 "json"，
        # 否则 API 会 400。caller 没写的话自动补一句兜底，避免调用方忘记。
        if response_format:
            body["response_format"] = response_format
            if (
                response_format.get("type") == "json_object"
                and "json" not in prompt.lower()
            ):
                body["messages"] = [
                    {"role": "user", "content": prompt + "\n\n(Response must be valid JSON.)"}
                ]
        if frequency_penalty is not None:
            body["frequency_penalty"] = frequency_penalty
        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=None) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                if response.status_code == 200:
                    data = response.json()
                    msg = data["choices"][0]["message"]
                    text = msg.get("content") or ""
                    # DeepSeek reasoner 等推理模型把思维链放 reasoning_content；
                    # 普通 chat 模型无此字段，保持 None 即可。
                    reasoning = msg.get("reasoning_content") or None
                    usage_raw = data.get("usage") or {}
                    usage = LLMUsage(
                        input_tokens=usage_raw.get("prompt_tokens", 0) or estimate_tokens(prompt),
                        output_tokens=usage_raw.get("completion_tokens", 0) or estimate_tokens(text),
                    )
                    return LLMResult(
                        text=text,
                        usage=usage,
                        cost_usd=compute_cost(self.model, usage),
                        latency_ms=int((time.monotonic() - start) * 1000),
                        provider=self._provider_name,
                        model=self.model,
                        finish_reason=data["choices"][0].get("finish_reason"),
                        reasoning=reasoning,
                    )
                logger.warning(
                    "[%s] API错误 status=%s url=%s body=%s",
                    self._provider_name, response.status_code,
                    f"{self.base_url}/chat/completions",
                    response.text[:200],
                )
        except httpx.TimeoutException as e:
            logger.warning(
                "[%s] HTTP timeout (%ss) — base_url=%s err=%r",
                self._provider_name, self.timeout, self.base_url, e,
            )
        except httpx.ConnectError as e:
            logger.warning(
                "[%s] 连接失败 — base_url=%s err=%r (检查网络/代理/DNS)",
                self._provider_name, self.base_url, e,
            )
        except Exception as e:
            # 关键修复：用 repr(e) 而非 str(e)，因为某些 httpx 异常 str() 为空字符串
            logger.warning(
                "[%s] 生成错误 type=%s repr=%r",
                self._provider_name, type(e).__name__, e,
            )
        return None

    async def generate_stream(
        self, prompt: str, temperature: float = 0.1
    ) -> AsyncIterator[LLMChunk]:
        if not self.api_key:
            logger.warning("[%s] 未配置API密钥", self._provider_name)
            return
        start = time.monotonic()
        accumulated = ""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": self.max_tokens,
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    },
                ) as response:
                    final_usage: Optional[LLMUsage] = None
                    finish: Optional[str] = None
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("choices") or []
                        if choices:
                            delta_obj = choices[0].get("delta") or {}
                            delta_text = delta_obj.get("content", "")
                            if delta_text:
                                accumulated += delta_text
                                yield LLMChunk(
                                    delta=delta_text,
                                    provider=self._provider_name,
                                    model=self.model,
                                )
                            if choices[0].get("finish_reason"):
                                finish = choices[0]["finish_reason"]
                        # usage is on final chunk when stream_options.include_usage
                        if data.get("usage"):
                            u = data["usage"]
                            final_usage = LLMUsage(
                                input_tokens=u.get("prompt_tokens", 0),
                                output_tokens=u.get("completion_tokens", 0),
                            )
                    if not final_usage:
                        final_usage = LLMUsage(
                            input_tokens=estimate_tokens(prompt),
                            output_tokens=estimate_tokens(accumulated),
                        )
                    yield LLMChunk(
                        delta="",
                        done=True,
                        usage=final_usage,
                        cost_usd=compute_cost(self.model, final_usage),
                        latency_ms=int((time.monotonic() - start) * 1000),
                        provider=self._provider_name,
                        model=self.model,
                        finish_reason=finish,
                    )
        except Exception as e:
            logger.warning(
                "[%s] 流式错误 type=%s repr=%r",
                self._provider_name, type(e).__name__, e,
            )
            yield LLMChunk(
                delta="",
                done=True,
                usage=LLMUsage(
                    input_tokens=estimate_tokens(prompt),
                    output_tokens=estimate_tokens(accumulated),
                ),
                latency_ms=int((time.monotonic() - start) * 1000),
                provider=self._provider_name,
                model=self.model,
                finish_reason="error",
            )

    async def check_connection(self) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "connected": False,
                "provider": self._provider_name,
                "error": "未配置API密钥"
            }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                if response.status_code == 200:
                    data = response.json()
                    models = [m["id"] for m in data.get("data", [])[:20]]
                    return {
                        "connected": True,
                        "provider": self._provider_name,
                        "available_models": models,
                        "current_model": self.model
                    }
        except Exception as e:
            logger.warning("[%s] 连接检查失败: %s", self._provider_name, e)
        return {
            "connected": False,
            "provider": self._provider_name,
            "error": f"无法连接到{self._provider_name}服务"
        }


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude API提供商"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "https://api.anthropic.com")
        self.model = config.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = config.get("max_tokens", 4096)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def generate_full(
        self, prompt: str, temperature: float = 0.1, max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        frequency_penalty: Optional[float] = None,
    ) -> Optional[LLMResult]:
        if not self.api_key:
            logger.warning("[Anthropic] 未配置API密钥")
            return None
        # Anthropic 原生不支持 frequency_penalty，参数接收但 no-op。
        _ = frequency_penalty
        # Anthropic 官方 API 不支持 OpenAI 风格的 response_format（JSON 强制走 tool_use 才能硬约束）。
        # 这里不做 tool_use 改造，仅在 caller 启用 JSON mode 时追加一句提示，让模型尽量返回 JSON。
        # 调用方的 regex parser 仍是最终兜底。
        if response_format and response_format.get("type") == "json_object" and "json" not in prompt.lower():
            prompt = prompt + "\n\n(Response must be valid JSON.)"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=None) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    text = ""
                    for block in data.get("content", []):
                        if block.get("type") == "text":
                            text = block["text"]
                            break
                    u = data.get("usage") or {}
                    usage = LLMUsage(
                        input_tokens=u.get("input_tokens", 0) or estimate_tokens(prompt),
                        output_tokens=u.get("output_tokens", 0) or estimate_tokens(text),
                    )
                    return LLMResult(
                        text=text,
                        usage=usage,
                        cost_usd=compute_cost(self.model, usage),
                        latency_ms=int((time.monotonic() - start) * 1000),
                        provider="anthropic",
                        model=self.model,
                        finish_reason=data.get("stop_reason"),
                    )
                logger.warning("[Anthropic] API错误 %s: %s", response.status_code, response.text[:200])
        except Exception as e:
            logger.warning("[Anthropic] 生成错误: %s", e)
        return None

    async def generate_stream(
        self, prompt: str, temperature: float = 0.1
    ) -> AsyncIterator[LLMChunk]:
        if not self.api_key:
            return
        start = time.monotonic()
        accumulated = ""
        input_tokens = 0
        output_tokens = 0
        finish: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": self.max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "stream": True,
                    },
                ) as response:
                    # Anthropic SSE format: "event: {type}\ndata: {json}\n\n"
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        event_type = data.get("type")
                        if event_type == "message_start":
                            u = (data.get("message") or {}).get("usage") or {}
                            input_tokens = u.get("input_tokens", 0)
                            output_tokens = u.get("output_tokens", 0)
                        elif event_type == "content_block_delta":
                            delta = data.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    accumulated += text
                                    yield LLMChunk(
                                        delta=text,
                                        provider="anthropic",
                                        model=self.model,
                                    )
                        elif event_type == "message_delta":
                            u = data.get("usage") or {}
                            if u.get("output_tokens"):
                                output_tokens = u["output_tokens"]
                            if data.get("delta", {}).get("stop_reason"):
                                finish = data["delta"]["stop_reason"]
                        elif event_type == "message_stop":
                            break
                    usage = LLMUsage(
                        input_tokens=input_tokens or estimate_tokens(prompt),
                        output_tokens=output_tokens or estimate_tokens(accumulated),
                    )
                    yield LLMChunk(
                        delta="",
                        done=True,
                        usage=usage,
                        cost_usd=compute_cost(self.model, usage),
                        latency_ms=int((time.monotonic() - start) * 1000),
                        provider="anthropic",
                        model=self.model,
                        finish_reason=finish,
                    )
        except Exception as e:
            logger.warning(
                "[Anthropic] 流式错误 type=%s repr=%r",
                type(e).__name__, e,
            )
            usage = LLMUsage(
                input_tokens=input_tokens or estimate_tokens(prompt),
                output_tokens=output_tokens or estimate_tokens(accumulated),
            )
            yield LLMChunk(
                delta="",
                done=True,
                usage=usage,
                cost_usd=compute_cost(self.model, usage),
                latency_ms=int((time.monotonic() - start) * 1000),
                provider="anthropic",
                model=self.model,
                finish_reason="error",
            )

    async def check_connection(self) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "connected": False,
                "provider": "anthropic",
                "error": "未配置API密钥"
            }
        # Anthropic没有list models端点，做一个轻量测试
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "Hi"}]
                    }
                )
                if response.status_code == 200:
                    return {
                        "connected": True,
                        "provider": "anthropic",
                        "available_models": [
                            "claude-sonnet-4-20250514",
                            "claude-haiku-4-5-20251001",
                            "claude-opus-4-6"
                        ],
                        "current_model": self.model
                    }
        except Exception as e:
            logger.warning("[Anthropic] 连接检查失败: %s", e)
        return {
            "connected": False,
            "provider": "anthropic",
            "error": "无法连接到Anthropic服务"
        }


class LLMProviderManager:
    """
    LLM提供商管理器
    管理多个LLM提供商，支持动态切换和回退
    """

    # 预定义的提供商配置模板
    PROVIDER_TEMPLATES = {
        "ollama": {
            "class": "OllamaProvider",
            "display_name": "本地Ollama",
            "description": "本地运行的Ollama模型（无需API密钥）",
            "requires_api_key": False,
            "default_models": ["llama3.2", "llama3.2:70b", "qwen2.5", "deepseek-r1"],
            "default_config": {
                "host": "http://localhost:11434",
                "model": "llama3.2"
            }
        },
        "openai": {
            "class": "OpenAICompatibleProvider",
            "display_name": "OpenAI",
            "description": "OpenAI GPT系列模型",
            "requires_api_key": True,
            "default_models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
            "default_config": {
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "provider_name": "openai"
            }
        },
        "anthropic": {
            "class": "AnthropicProvider",
            "display_name": "Anthropic Claude",
            "description": "Anthropic Claude系列模型",
            "requires_api_key": True,
            "default_models": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
            "default_config": {
                "base_url": "https://api.anthropic.com",
                "model": "claude-sonnet-4-20250514"
            }
        },
        "deepseek": {
            "class": "OpenAICompatibleProvider",
            "display_name": "DeepSeek",
            "description": "DeepSeek系列模型（性价比高）",
            "requires_api_key": True,
            "default_models": ["deepseek-chat", "deepseek-reasoner"],
            "default_config": {
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "provider_name": "deepseek"
            }
        },
        "moonshot": {
            "class": "OpenAICompatibleProvider",
            "display_name": "Moonshot (月之暗面)",
            "description": "Moonshot Kimi系列模型",
            "requires_api_key": True,
            "default_models": ["moonshot-v1-8k", "moonshot-v1-32k"],
            "default_config": {
                "base_url": "https://api.moonshot.cn/v1",
                "model": "moonshot-v1-8k",
                "provider_name": "moonshot"
            }
        },
        "jiekou": {
            "class": "AnthropicProvider",
            "display_name": "Jiekou.ai 中转",
            "description": "jiekou.ai API中转（Anthropic 兼容），支持 Claude 等模型",
            "requires_api_key": True,
            "default_models": [
                "claude-sonnet-4-20250514",
                "claude-sonnet-4-6",
                "claude-opus-4-6",
                "gpt-5.4-mini",
                "gemini-3.1-pro-preview",
                "deepseek/deepseek-v3.1",
            ],
            "default_config": {
                "base_url": "https://api.jiekou.ai/openai",
                "model": "claude-sonnet-4-20250514",
                "provider_name": "jiekou",
                "max_tokens": 4000,
                "timeout": 120.0,
            }
        },
        "custom": {
            "class": "OpenAICompatibleProvider",
            "display_name": "自定义API",
            "description": "兼容OpenAI接口的自定义API端点",
            "requires_api_key": True,
            "default_models": [],
            "default_config": {
                "base_url": "",
                "model": "",
                "provider_name": "custom"
            }
        }
    }

    PROVIDER_CLASSES = {
        "OllamaProvider": OllamaProvider,
        "OpenAICompatibleProvider": OpenAICompatibleProvider,
        "AnthropicProvider": AnthropicProvider,
    }

    def __init__(self, default_ollama_host: str = "http://localhost:11434"):
        self.providers: Dict[str, BaseLLMProvider] = {}
        self.active_provider_id: str = "ollama"
        self.default_ollama_host = default_ollama_host

        # 初始化默认Ollama提供商
        self._init_default_provider()

    def _init_default_provider(self):
        """初始化默认的Ollama提供商"""
        self.providers["ollama"] = OllamaProvider({
            "host": self.default_ollama_host,
            "model": "llama3.2"
        })

    def configure_provider(self, provider_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        配置一个LLM提供商
        
        Args:
            provider_id: 提供商ID（ollama/openai/anthropic/deepseek/moonshot/custom）
            config: 配置字典，可包含api_key, model, base_url等
        
        Returns:
            配置结果
        """
        template = self.PROVIDER_TEMPLATES.get(provider_id)
        if not template:
            return {"success": False, "error": f"未知的提供商: {provider_id}"}

        # 合并默认配置和用户配置
        full_config = {**template["default_config"], **config}

        # 检查必需的API密钥
        if template["requires_api_key"] and not full_config.get("api_key"):
            return {"success": False, "error": "该提供商需要API密钥"}

        # 创建提供商实例
        provider_class_name = template["class"]
        provider_class = self.PROVIDER_CLASSES.get(provider_class_name)
        if not provider_class:
            return {"success": False, "error": f"未找到提供商类: {provider_class_name}"}

        try:
            provider = provider_class(full_config)
            self.providers[provider_id] = provider

            # 检测构造过程中被 clamp 的参数，回报给前端，避免静默改值造成 UI 误导
            warnings: List[str] = []
            requested_max = config.get("max_tokens")
            actual_max = getattr(provider, "max_tokens", None)
            if requested_max and actual_max and int(actual_max) != int(requested_max):
                warnings.append(
                    f"max_tokens 请求值 {requested_max} 超过该提供商/模型的上限，已调整为 {actual_max}"
                )

            return {
                "success": True,
                "provider": provider_id,
                "model": full_config.get("model"),
                "max_tokens": actual_max,
                "warnings": warnings,
                "message": f"已配置 {template['display_name']}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_active_provider(self, provider_id: str) -> Dict[str, Any]:
        """设置活跃的LLM提供商"""
        if provider_id not in self.providers:
            return {"success": False, "error": f"提供商 {provider_id} 尚未配置"}
        self.active_provider_id = provider_id
        return {"success": True, "active_provider": provider_id}

    def get_active_provider(self) -> Optional[BaseLLMProvider]:
        """获取当前活跃的提供商"""
        return self.providers.get(self.active_provider_id)

    async def generate(
        self, prompt: str, temperature: float = 0.1, max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        frequency_penalty: Optional[float] = None,
    ) -> Optional[str]:
        """
        Backward-compat wrapper that delegates to generate_full() so all LLM calls
        fire observability hooks via the manager's unified instrumentation.
        """
        result = await self.generate_full(
            prompt, temperature, max_tokens=max_tokens,
            response_format=response_format,
            frequency_penalty=frequency_penalty,
        )
        return result.text if result else None

    async def generate_full(
        self, prompt: str, temperature: float = 0.1, max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        frequency_penalty: Optional[float] = None,
    ) -> Optional[LLMResult]:
        """Try active provider's generate_full, fall back to other cloud providers.

        Fires LLM_CALL_START before and LLM_CALL_END after. Hook firing is
        wrapped in try/except so observability failures never crash LLM calls.

        B1: Prompt cache — 只对 temperature ≤ 0.4 的确定性调用启用。
        命中时合成 LLMResult(cost_usd=0, latency_ms=0, finish_reason="cache_hit")
        并依然 fire LLM_CALL_END Hook 以便 DevTools 可见。
        """
        call_id = uuid.uuid4().hex[:12]
        llm_ctx = get_llm_context()
        active_pid = self.active_provider_id or "unknown"

        # M3 BYOK 透传：检查 ContextVar，per-request 用临时 provider 替换全局 active
        # Celery worker 不传播 ContextVar → 默认 None → 走原全局逻辑（spec §4.3 一致）
        from app.services.core.llm_request_context import llm_override_var
        _byok_override = llm_override_var.get()
        _byok_provider = None
        if _byok_override:
            from app.services.core.llm_request_resolver import _build_temp_provider
            _byok_provider = _build_temp_provider(_byok_override)

        if _byok_provider is not None:
            active_provider = _byok_provider
            active_pid = f"byok:{_byok_override['provider']}"
        else:
            active_provider = self.get_active_provider()
        active_model = getattr(active_provider, "model", "") if active_provider else ""

        # Fire LLM_CALL_START (best-effort, never crash the call)
        try:
            from app.harness.hook_engine import HookEngine, HookPoint
            await HookEngine.get_instance().fire(HookPoint.LLM_CALL_START, {
                "call_id": call_id,
                "provider": active_pid,
                "model": active_model or None,
                "prompt_preview": prompt[:200],
                "agent_name": llm_ctx.agent_name,
                "session_id": llm_ctx.session_id,
                "round_id": llm_ctx.round_id,
            })
        except Exception:
            pass

        # B1: Try prompt cache first (temperature ≤ 0.4 only, via should_cache)
        cache_hit = False
        try:
            from app.services.core.llm_cache import try_get_cached
            cached_text = await try_get_cached(
                prompt, temperature, active_pid, active_model,
                response_format=response_format,
            )
        except Exception:
            cached_text = None

        if cached_text:
            cache_hit = True
            cache_usage = LLMUsage(
                input_tokens=estimate_tokens(prompt),
                output_tokens=estimate_tokens(cached_text),
            )
            result: Optional[LLMResult] = LLMResult(
                text=cached_text,
                usage=cache_usage,
                cost_usd=0.0,
                latency_ms=0,
                provider=active_pid,
                model=active_model or "cache",
                finish_reason="cache_hit",
            )
        else:
            provider = active_provider
            result = None
            if provider:
                r = await provider.generate_full(
                    prompt, temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    frequency_penalty=frequency_penalty,
                )
                if r and r.text:
                    result = r

            if result is None:
                for pid, p in self.providers.items():
                    if pid == self.active_provider_id or pid == "ollama":
                        continue
                    r = await p.generate_full(
                        prompt, temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        frequency_penalty=frequency_penalty,
                    )
                    if r and r.text:
                        logger.info("[LLM] generate_full 回退到: %s", pid)
                        result = r
                        break

            # B1: Store in cache on success
            if result and result.text:
                try:
                    from app.services.core.llm_cache import set_cached
                    from app.config import settings as _settings
                    ttl = getattr(_settings, "llm_cache_ttl_seconds", 7200)
                    await set_cached(
                        prompt, temperature, active_pid,
                        result.model or active_model,
                        result.text, ttl_seconds=ttl,
                        response_format=response_format,
                    )
                except Exception:
                    pass

        # Fire LLM_CALL_END (best-effort)
        try:
            from app.harness.hook_engine import HookEngine, HookPoint
            reasoning_full = result.reasoning if result else None
            end_ctx = {
                "call_id": call_id,
                "provider": result.provider if result else active_pid,
                "model": result.model if result else None,
                "usage": {
                    "input_tokens": result.usage.input_tokens if result else 0,
                    "output_tokens": result.usage.output_tokens if result else 0,
                },
                "cost_usd": result.cost_usd if result else 0.0,
                "latency_ms": result.latency_ms if result else 0,
                "finish_reason": result.finish_reason if result else "error",
                "text_preview": (result.text[:200] if result else ""),
                # deepseek-reasoner 等推理模型的思维链（DevTools 可折叠展示）
                "reasoning_preview": (reasoning_full[:500] if reasoning_full else None),
                "reasoning_length": len(reasoning_full) if reasoning_full else 0,
                "agent_name": llm_ctx.agent_name,
                "session_id": llm_ctx.session_id,
                "round_id": llm_ctx.round_id,
                "status": "ok" if result else "error",
                "cache": "hit" if cache_hit else "miss",
            }
            await HookEngine.get_instance().fire(HookPoint.LLM_CALL_END, end_ctx)
        except Exception:
            pass

        return result

    async def generate_stream(
        self, prompt: str, temperature: float = 0.1
    ) -> AsyncIterator[LLMChunk]:
        """Stream from active provider. No automatic fallback (caller decides).

        If the active provider fails mid-stream, the final chunk will have
        finish_reason="error" — caller can detect and retry with generate_full.

        Fires LLM_CALL_START before iterating and LLM_CALL_END after the stream
        completes, based on the accumulated final chunk.
        """
        call_id = uuid.uuid4().hex[:12]
        llm_ctx = get_llm_context()

        try:
            from app.harness.hook_engine import HookEngine, HookPoint
            await HookEngine.get_instance().fire(HookPoint.LLM_CALL_START, {
                "call_id": call_id,
                "provider": self.active_provider_id,
                "model": getattr(self.get_active_provider(), "model", None) if self.get_active_provider() else None,
                "prompt_preview": prompt[:200],
                "agent_name": llm_ctx.agent_name,
                "session_id": llm_ctx.session_id,
                "round_id": llm_ctx.round_id,
            })
        except Exception:
            pass

        provider = self.get_active_provider()
        if not provider:
            return

        final_chunk: Optional[LLMChunk] = None
        accumulated = ""
        async for chunk in provider.generate_stream(prompt, temperature):
            if chunk.delta:
                accumulated += chunk.delta
            if chunk.done:
                final_chunk = chunk
            yield chunk

        # Fire LLM_CALL_END after stream completes
        try:
            from app.harness.hook_engine import HookEngine, HookPoint
            if final_chunk:
                end_ctx = {
                    "call_id": call_id,
                    "provider": final_chunk.provider or self.active_provider_id,
                    "model": final_chunk.model,
                    "usage": {
                        "input_tokens": final_chunk.usage.input_tokens if final_chunk.usage else 0,
                        "output_tokens": final_chunk.usage.output_tokens if final_chunk.usage else 0,
                    },
                    "cost_usd": final_chunk.cost_usd,
                    "latency_ms": final_chunk.latency_ms,
                    "finish_reason": final_chunk.finish_reason,
                    "text_preview": accumulated[:200],
                    "agent_name": llm_ctx.agent_name,
                    "session_id": llm_ctx.session_id,
                    "round_id": llm_ctx.round_id,
                    "status": "error" if final_chunk.finish_reason == "error" else "ok",
                }
                await HookEngine.get_instance().fire(HookPoint.LLM_CALL_END, end_ctx)
        except Exception:
            pass

    async def check_all_connections(self) -> Dict[str, Any]:
        """检查所有已配置提供商的连接状态"""
        statuses = {}
        for pid, provider in self.providers.items():
            statuses[pid] = await provider.check_connection()
        return {
            "active_provider": self.active_provider_id,
            "providers": statuses
        }

    async def check_active_connection(self) -> Dict[str, Any]:
        """只检查活跃提供商的连接状态"""
        provider = self.get_active_provider()
        if provider:
            status = await provider.check_connection()
            status["is_active"] = True
            return status
        return {"connected": False, "error": "无活跃提供商"}

    def get_available_providers(self) -> List[Dict]:
        """获取所有可用的提供商模板信息"""
        result = []
        for pid, template in self.PROVIDER_TEMPLATES.items():
            # 若该提供商已配置，取实际使用的 model 和 max_tokens
            model = None
            max_tokens = None
            if pid in self.providers:
                model = getattr(self.providers[pid], "model", None)
                max_tokens = getattr(self.providers[pid], "max_tokens", None)
            info = {
                "provider_id": pid,               # 前端使用 p.provider_id
                "display_name": template["display_name"],
                "description": template["description"],
                "requires_api_key": template["requires_api_key"],
                "default_models": template["default_models"],
                "model": model,                   # 已配置时显示当前模型名
                "max_tokens": max_tokens,         # 已配置时显示当前 max_tokens
                "configured": pid in self.providers,
                "active": pid == self.active_provider_id,
            }
            result.append(info)
        return result

    def remove_provider(self, provider_id: str) -> Dict[str, Any]:
        """移除一个提供商配置"""
        if provider_id == "ollama":
            return {"success": False, "error": "不能移除默认的Ollama提供商"}
        if provider_id in self.providers:
            del self.providers[provider_id]
            if self.active_provider_id == provider_id:
                self.active_provider_id = "ollama"
            return {"success": True, "message": f"已移除 {provider_id}"}
        return {"success": False, "error": f"提供商 {provider_id} 未配置"}

    def to_config_dict(self) -> Dict[str, Any]:
        """序列化当前所有提供商配置为可持久化的字典"""
        providers_data = {}
        for pid, provider in self.providers.items():
            p_data = {}
            for attr in ("model", "api_key", "base_url", "host", "max_tokens"):
                val = getattr(provider, attr, None)
                if val:
                    p_data[attr] = val
            if hasattr(provider, "_provider_name"):
                p_data["provider_name"] = provider._provider_name
            providers_data[pid] = p_data
        return {
            "active_provider_id": self.active_provider_id,
            "providers": providers_data,
        }

    def restore_from_config_dict(self, data: Dict[str, Any]) -> None:
        """从配置字典恢复提供商状态"""
        for pid, p_config in data.get("providers", {}).items():
            result = self.configure_provider(pid, p_config)
            if not result.get("success"):
                logger.warning("[LLMManager] 恢复配置失败 %s: %s", pid, result.get('error'))
        active = data.get("active_provider_id", "ollama")
        if active in self.providers:
            self.active_provider_id = active
