from __future__ import annotations

from app.services.core.llm_types import (
    LLMUsage, LLMResult, LLMChunk,
    compute_cost, estimate_tokens, TOKEN_PRICING,
)


class TestLLMUsage:
    def test_total_tokens(self):
        u = LLMUsage(input_tokens=100, output_tokens=50)
        assert u.total_tokens == 150

    def test_defaults(self):
        u = LLMUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.total_tokens == 0


class TestComputeCost:
    def test_claude_opus(self):
        u = LLMUsage(input_tokens=1_000_000, output_tokens=500_000)
        cost = compute_cost("claude-opus-4-6", u)
        # 1M input @ $15 + 0.5M output @ $75 = $15 + $37.5 = $52.5
        assert cost == 52.5

    def test_deepseek(self):
        u = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = compute_cost("deepseek-chat", u)
        assert cost == round(0.14 + 0.28, 6)

    def test_ollama_free(self):
        u = LLMUsage(input_tokens=1000, output_tokens=1000)
        assert compute_cost("llama3.2", u) == 0.0

    def test_unknown_model(self):
        u = LLMUsage(input_tokens=1000, output_tokens=1000)
        assert compute_cost("unknown-model-xyz", u) == 0.0

    def test_partial_match(self):
        # "claude-sonnet-4-20250514" is in pricing, any variant that contains it matches
        u = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        # exact match
        c1 = compute_cost("claude-sonnet-4-20250514", u)
        assert c1 == round(3.0 + 15.0, 6)


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0  # handled by falsy check

    def test_ascii(self):
        assert estimate_tokens("hello world") >= 1
        assert estimate_tokens("a" * 30) == 10  # 30 / 3

    def test_min_one(self):
        assert estimate_tokens("x") == 1


class TestTokenPricing:
    def test_has_claude(self):
        assert "claude-opus-4-6" in TOKEN_PRICING
        assert "claude-sonnet-4-6" in TOKEN_PRICING

    def test_has_deepseek(self):
        assert "deepseek-chat" in TOKEN_PRICING

    def test_ollama_zero_cost(self):
        assert TOKEN_PRICING["llama3.2"] == (0.0, 0.0)
