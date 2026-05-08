"""Concrete pipeline phases that together replace the monolithic
``_execute_round_async`` body in ``app/workers/search_tasks.py``.

Order is implicit via deps; the runner topologically sorts them. To add a
phase: create a new file here, expose its class, and register the instance in
``build_default_round_pipeline`` (search_tasks.py)."""
from .apply_search_mode import ApplySearchModePhase
from .build_dedup import BuildDedupPhase
from .dispatch_summaries import DispatchSummariesPhase
from .fetch import FetchPhase
from .load_confirmed_keywords import LoadConfirmedKeywordsPhase
from .load_memory import LoadMemoryPhase
from .load_round import LoadRoundPhase
from .plan_query import PlanQueryPhase
from .rerank import RerankPhase
from .save_docs import SaveDocsPhase
from .score import ScorePhase

__all__ = [
    "ApplySearchModePhase",
    "BuildDedupPhase",
    "DispatchSummariesPhase",
    "FetchPhase",
    "LoadConfirmedKeywordsPhase",
    "LoadMemoryPhase",
    "LoadRoundPhase",
    "PlanQueryPhase",
    "RerankPhase",
    "SaveDocsPhase",
    "ScorePhase",
]
