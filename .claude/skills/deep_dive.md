# Deep Dive Skill

Find related work for a highly-rated paper.

## Trigger
User action: click "Deep Dive" on a paper rated "very relevant" (relevance=2).

## API
`POST /api/skills/{project_id}/deep_dive/run` with `{"document_id": "uuid"}`

## Cost
~1 LLM call ($0.003 with DeepSeek)

## Implementation
`backend/app/harness/skills/deep_dive.py`
