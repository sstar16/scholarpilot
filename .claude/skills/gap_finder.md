# Gap Finder Skill

Identify research gaps from user feedback patterns.

## Trigger
Available after round 3. User action: click "Gap Finder" in Skills panel.

## API
`POST /api/skills/{project_id}/gap_finder/run`

## Cost
~1 LLM call ($0.003)

## Implementation
`backend/app/harness/skills/gap_finder.py`
