# Hook System

ScholarPilot's hook engine fires at lifecycle boundaries in the search pipeline.

## Available Hook Points

| Hook Point | Fires When | Context |
|---|---|---|
| ROUND_START | Round begins execution | round_id, round_number, project_id |
| POST_SEARCH | All fetchers complete | round_id, total_candidates, source_stats |
| PRE_SCORING | Before relevance scoring | round_id, doc_count |
| POST_SCORING | After scoring complete | round_id, selected_count |
| PRE_SUMMARIZE | Before LLM summarization | round_id, doc_count |
| POST_SUMMARIZE | After all summaries done | round_id, summary_count |
| ROUND_COMPLETE | Round fully finished | round_id |
| PRE_FEEDBACK | Before profile update | round_id, feedback_count |
| POST_FEEDBACK | After profile updated | round_id, feedback_count |
| PROJECT_CREATE | New project created | project_id |
| MONITOR_TRIGGER | Daily monitor fires | monitor_job_id |

## Built-in Hooks
- `logging_hook` — Structured JSON logs at every hook point
- `metrics_hook` — In-memory counters (rounds, source latency, etc.)

## Adding Custom Hooks
```python
from app.harness.hook_engine import HookEngine, HookPoint

async def my_hook(context):
    # Do something with context
    return context

engine = HookEngine.get_instance()
engine.register(HookPoint.POST_SEARCH, my_hook, name="my_hook", priority=50)
```
