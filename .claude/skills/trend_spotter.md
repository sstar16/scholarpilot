# Trend Spotter Skill

Identify emerging research trends from accumulated search results.

## Trigger
Available after round 3. User action: click "Trend Spotter" in Skills panel.

## API
`POST /api/skills/{project_id}/trend_spotter/run`

## Cost
~1 LLM call ($0.003)

## Implementation
`backend/app/harness/skills/trend_spotter.py`
