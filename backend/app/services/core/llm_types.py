"""
LLM response types and token usage tracking.

LLMResult: full non-streaming response with usage + cost + latency
LLMChunk: streaming chunk (delta + optional final usage)
TOKEN_PRICING: per-model USD pricing (input, output) per 1M tokens
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMUsage:
    """Token usage for a single LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResult:
    """Full result of a non-streaming LLM call.

    reasoning: 思维链文本（仅 deepseek-reasoner 等推理模型返回；通过
    `choices[0].message.reasoning_content` 解析。非推理模型为 None）。
    """
    text: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    cost_usd: float = 0.0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    finish_reason: Optional[str] = None
    reasoning: Optional[str] = None


@dataclass
class LLMChunk:
    """Single chunk from a streaming LLM call.

    - `delta`: text appended to the stream since last chunk (may be empty on metadata chunks)
    - `done`: True on the final chunk (carrying usage totals)
    - `usage`: only populated on final chunk (LLMUsage with totals)
    - `cost_usd`: final cumulative cost (only on done chunk)
    - `latency_ms`: cumulative latency (only on done chunk)
    """
    delta: str = ""
    done: bool = False
    usage: Optional[LLMUsage] = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    finish_reason: Optional[str] = None


# USD per 1M tokens — (input_price, output_price)
# Sources: official pricing pages as of 2026-04.
TOKEN_PRICING: dict[str, tuple[float, float]] = {
    # Claude 4.x series
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    # OpenAI
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-5.4-mini": (0.25, 1.0),  # jiekou alias
    # DeepSeek
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek/deepseek-v3.1": (0.27, 1.10),
    # Moonshot
    "moonshot-v1-8k": (0.17, 0.17),
    "moonshot-v1-32k": (0.34, 0.34),
    "moonshot-v1-128k": (0.84, 0.84),
    # Gemini via jiekou
    "gemini-3.1-pro-preview": (1.25, 5.0),
    # Ollama (local, free)
    "llama3.2": (0.0, 0.0),
    "llama3.2:70b": (0.0, 0.0),
    "qwen2.5": (0.0, 0.0),
    "deepseek-r1": (0.0, 0.0),
}


def compute_cost(model: str, usage: LLMUsage) -> float:
    """Compute USD cost for a given model + usage. Returns 0.0 for unknown models."""
    prices = TOKEN_PRICING.get(model)
    if not prices:
        # Fallback: try partial matches
        for key, val in TOKEN_PRICING.items():
            if key in model or model in key:
                prices = val
                break
    if not prices:
        return 0.0
    input_per_m, output_per_m = prices
    return round(
        (usage.input_tokens / 1_000_000) * input_per_m
        + (usage.output_tokens / 1_000_000) * output_per_m,
        6,
    )


def estimate_tokens(text: str) -> int:
    """Rough estimate for providers without usage reporting (Ollama sometimes).

    Rule: ~4 chars per token for English, ~2 chars per CJK char.
    For mixed text: len(text) / 3 is a practical approximation.
    """
    if not text:
        return 0
    return max(1, len(text) // 3)
