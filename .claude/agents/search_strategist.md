# Search Strategist Agent

Agent that dynamically plans search strategy for each round.

## When Active
Only when `ENABLE_AGENT_PLANNING=true` in `.env`.

## What It Does
Given a research topic, round number, user profile, and tool reliability stats,
produces a `AgentSearchPlan` that overrides the default round config.

## Prompt Template
See `backend/app/harness/prompts/search_strategy.py`

## Cost
~$0.0001 per call with DeepSeek. Cached in Redis (1 hour TTL).

## Fallback
If LLM fails, the deterministic `build_query()` path runs unchanged.
