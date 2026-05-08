"""轻量结构化事件 telemetry sink — sp-api 版（与 backend 同源）。

For UX experiments (stale_hint, feature flags) — answer "did people click this?"
with a sample size of 100-1000 events. So this is just structured logger lines
+ optional jsonl mirror for offline grep/jq.

Privacy: project_id / user_id 是 UUID，无 PII。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_JSONL_PATH_ENV = "TELEMETRY_JSONL_PATH"
_DEFAULT_JSONL = "/app/data/telemetry.jsonl"

# 客户端可能 emit 的事件白名单 — 客户端要新增事件先 PR 加这里。
KNOWN_EVENTS = frozenset({
    "stale_hint_impression",
    "stale_hint_dismissed",
    "stale_hint_clicked",
    "client_run_started",
    "client_run_finished",
    "client_pdf_downloaded",
})


def emit(event: str, **fields: Any) -> None:
    """Record a single structured event. Never raises."""
    try:
        if event not in KNOWN_EVENTS:
            logger.warning("[telemetry] unknown event %r — recording anyway", event)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **{k: _safe(v) for k, v in fields.items()},
        }
        logger.info("[telemetry] %s", event, extra={"telemetry": record})
        path = os.getenv(_JSONL_PATH_ENV) or _DEFAULT_JSONL
        if path:
            _append_jsonl(Path(path), record)
    except Exception as e:
        logger.warning("[telemetry] emit failed for %s: %s", event, e)


def _safe(value: Any) -> Any:
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
        pass
