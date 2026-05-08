#!/usr/bin/env python3
"""Aggregate the telemetry jsonl into stale-hint funnel stats.

Usage:
    python scripts/analyze_telemetry.py [path/to/telemetry.jsonl]
    # default: /app/data/telemetry.jsonl

Output (per-day):
    date  impr  click  dismiss  ignore  CTR%  Dismiss%  Ignore%

CTR     = clicked / impressions
Dismiss = dismissed / impressions  (user explicitly muted)
Ignore  = (impr - clicked - dismissed) / impressions  (didn't engage)

A user can both ignore and later click — we count the LAST action per
(user_id, project_id) on the same day as the canonical outcome. So
``CTR + Dismiss + Ignore == 100%`` per day.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


_DEFAULT_PATH = Path("/app/data/telemetry.jsonl")


def iter_records(path: Path) -> Iterable[dict]:
    if not path.exists():
        print(f"telemetry file not found: {path}", file=sys.stderr)
        return []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def analyse(records: Iterable[dict]) -> dict[str, dict]:
    """Group by date, count impressions / clicks / dismisses uniquely per
    (user_id, project_id) so a user repeatedly seeing the same hint counts
    as one impression for that day."""
    per_day: dict[str, dict[str, set[tuple]]] = defaultdict(
        lambda: {"impr": set(), "click": set(), "dismiss": set()},
    )
    for r in records:
        ts = r.get("ts", "")
        date = ts[:10] if len(ts) >= 10 else "unknown"
        ev = r.get("event")
        key = (r.get("user_id"), r.get("project_id"))
        if ev == "stale_hint_impression":
            per_day[date]["impr"].add(key)
        elif ev == "stale_hint_clicked":
            per_day[date]["click"].add(key)
        elif ev == "stale_hint_dismissed":
            per_day[date]["dismiss"].add(key)
    out: dict[str, dict] = {}
    for date in sorted(per_day):
        day = per_day[date]
        impr = day["impr"]
        click = day["click"] & impr
        dismiss = (day["dismiss"] - click) & impr
        ignored = impr - click - dismiss
        n = len(impr)
        out[date] = {
            "impr": n,
            "click": len(click),
            "dismiss": len(dismiss),
            "ignore": len(ignored),
            "ctr": (len(click) / n * 100) if n else 0.0,
            "dismiss_rate": (len(dismiss) / n * 100) if n else 0.0,
            "ignore_rate": (len(ignored) / n * 100) if n else 0.0,
        }
    return out


def render_table(stats: dict[str, dict]) -> str:
    if not stats:
        return "(no telemetry events found)"
    header = f"{'date':12s} {'impr':>5s} {'click':>5s} {'dismiss':>7s} " \
             f"{'ignore':>6s} {'CTR%':>6s} {'Dismiss%':>9s} {'Ignore%':>8s}"
    rows = [header, "-" * len(header)]
    for date, s in stats.items():
        rows.append(
            f"{date:12s} {s['impr']:>5d} {s['click']:>5d} "
            f"{s['dismiss']:>7d} {s['ignore']:>6d} "
            f"{s['ctr']:>6.1f} {s['dismiss_rate']:>9.1f} {s['ignore_rate']:>8.1f}",
        )
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else _DEFAULT_PATH
    stats = analyse(iter_records(path))
    print(render_table(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
