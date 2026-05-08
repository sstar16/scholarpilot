"""Lightweight structured-event telemetry sink.

For UX experiments (stale_hint, future feature flags) we don't need a full
analytics pipeline — we need to answer "did people click this?" / "did the
threshold help?" with a sample size of 100-1000 events. So this is just:

  - one logger line per event with structured ``extra``
  - one optional jsonl file mirror for offline grep/jq

Reading these later: ``scripts/analyze_telemetry.py`` (see same dir) walks
the jsonl, groups by event name, prints CTR / dismiss / ignore rates.

Privacy note: project_id and user_id are UUIDs, no PII. Don't put doc titles
or query strings in here.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_JSONL_PATH_ENV = "TELEMETRY_JSONL_PATH"   # blank/unset → no file mirror
_DEFAULT_JSONL = "/app/data/telemetry.jsonl"

# Whitelist of recognised events. Adding a new event = adding a name here.
# Keeps grep/analysis scripts honest.
KNOWN_EVENTS = frozenset({
    "stale_hint_impression",
    "stale_hint_dismissed",
    "stale_hint_clicked",
})


def emit(event: str, **fields: Any) -> None:
    """Record a single structured event. Never raises — telemetry must not
    break the request path."""
    try:
        if event not in KNOWN_EVENTS:
            logger.warning("[telemetry] unknown event %r — recording anyway", event)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **{k: _safe(v) for k, v in fields.items()},
        }
        # 1) structured logger line
        logger.info("[telemetry] %s", event, extra={"telemetry": record})
        # 2) optional jsonl mirror (best-effort)
        path = os.getenv(_JSONL_PATH_ENV) or _DEFAULT_JSONL
        if path:
            _append_jsonl(Path(path), record)
    except Exception as e:
        logger.warning("[telemetry] emit failed for %s: %s", event, e)


def _safe(value: Any) -> Any:
    """Coerce values to JSON-safe primitives. UUIDs / datetimes / Path → str."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return str(value)


def _append_jsonl(path: Path, record: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Don't propagate — the logger line is still durable in container logs.
        pass
