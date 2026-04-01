# LLM Cost Budget Rules

## Per-Round Limits
- Agent planning: ~$0.0001 (DeepSeek, cached)
- Summarization: ~$0.003 per doc (10 docs/round = ~$0.03)
- Total per round: < $0.05 (configurable via `MAX_LLM_COST_PER_ROUND`)

## Per-Skill Limits
- Each skill: ~$0.003 per invocation
- Skills are user-triggered only (no idle cost)

## Cost Controls
1. `ENABLE_AGENT_PLANNING=false` (default) — zero agent LLM cost
2. Redis caching for agent plans (1 hour TTL)
3. DeepSeek as default planning provider ($0.14/M tokens)
4. Hard budget ceiling in config
