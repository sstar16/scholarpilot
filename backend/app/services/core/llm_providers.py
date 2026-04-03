#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多LLM提供商抽象层
支持：本地Ollama、OpenAI API、Anthropic Claude API、DeepSeek API、自定义API端点
用户可自行配置API密钥和模型选择
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import httpx


class BaseLLMProvider(ABC):
    """LLM提供商基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.timeout = config.get("timeout", 60.0)

    @abstractmethod
    async def generate(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        """生成文本响应"""
        pass

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

    async def generate(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=None) as client:
                response = await client.post(
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": 500
                        }
                    }
                )
                if response.status_code == 200:
                    return response.json().get("response", "")
        except Exception as e:
            print(f"[Ollama] 生成错误: {e}")
        return None

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
            print(f"[Ollama] 连接检查失败: {e}")
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

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def generate(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        if not self.api_key:
            print(f"[{self._provider_name}] 未配置API密钥")
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": temperature,
                        "max_tokens": self.max_tokens,
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    print(f"[{self._provider_name}] API错误 {response.status_code}: {response.text[:200]}")
        except Exception as e:
            print(f"[{self._provider_name}] 生成错误: {e}")
        return None

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
            print(f"[{self._provider_name}] 连接检查失败: {e}")
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

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def generate(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        if not self.api_key:
            print("[Anthropic] 未配置API密钥")
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "max_tokens": 500,
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": temperature
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    for block in data.get("content", []):
                        if block.get("type") == "text":
                            return block["text"]
                else:
                    print(f"[Anthropic] API错误 {response.status_code}: {response.text[:200]}")
        except Exception as e:
            print(f"[Anthropic] 生成错误: {e}")
        return None

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
            print(f"[Anthropic] 连接检查失败: {e}")
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
            "class": "OpenAICompatibleProvider",
            "display_name": "Jiekou.ai 中转",
            "description": "jiekou.ai API中转，支持 Claude/GPT/Gemini 等多种模型",
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
            return {
                "success": True,
                "provider": provider_id,
                "model": full_config.get("model"),
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

    async def generate(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        """
        使用活跃提供商生成文本，失败时自动回退到其他提供商
        """
        # 先尝试活跃提供商
        provider = self.get_active_provider()
        if provider:
            result = await provider.generate(prompt, temperature)
            if result:
                return result

        # 回退到其他已配置的提供商
        for pid, p in self.providers.items():
            if pid != self.active_provider_id:
                result = await p.generate(prompt, temperature)
                if result:
                    print(f"[LLM] 回退到提供商: {pid}")
                    return result

        return None

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
                print(f"[LLMManager] 恢复配置失败 {pid}: {result.get('error')}")
        active = data.get("active_provider_id", "ollama")
        if active in self.providers:
            self.active_provider_id = active
