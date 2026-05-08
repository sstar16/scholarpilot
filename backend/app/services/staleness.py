"""Staleness service — detect when a project has gone too long without a
completed search round, then nudge the user via a soft rich-message hint.

Three knobs on Settings:
  - stale_days_threshold  (default 7)  : when to start nudging
  - stale_dedup_hours     (default 24) : don't repeat the hint within this window
  - stale_dismiss_days    (default 7)  : silenced for this long if user dismisses

Decision flow:
  ┌─ check_and_inject_stale_hint(project_id, db)
  │
  ├── 1) Look up last completed round
  │      no rounds yet?     → not stale (None days_ago)
  │
  ├── 2) Has the user dismissed recently?
  │      dismissed_until > now? → not stale (suppressed)
  │
  ├── 3) days_ago >= stale_days_threshold?
  │      no?  → not stale (returns days_ago for UI)
  │
  ├── 4) Already a stale_hint in the last stale_dedup_hours window?
  │      yes? → already nudged, return without re-injecting
  │
  └── 5) inject rich message + return is_stale=True
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.services.conversation_inject import inject_rich_message

logger = logging.getLogger(__name__)


# Lazy access to model classes — pulling them at module load drags in
# app.database / asyncpg, which bloats the import graph and breaks unit tests
# in environments without postgres deps installed.

def _SearchRound():  # noqa: N802 — factory pattern for lazy model resolution
    from app.models.search_round import SearchRound
    return SearchRound


def _ConversationSession():  # noqa: N802
    from app.models.conversation_session import ConversationSession
    return ConversationSession


@dataclass
class StaleStatus:
    is_stale: bool
    days_ago: Optional[int]            # None ⇔ no completed rounds yet
    threshold_days: int
    suppressed_until: Optional[datetime] = None  # set when user dismissed recently
    just_injected: bool = False        # True ⇔ this call inserted a fresh hint


async def check_and_inject_stale_hint(
    project_id: uuid.UUID,
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    threshold_days: Optional[int] = None,
    dedup_hours: Optional[int] = None,
) -> StaleStatus:
    """Compute staleness and conditionally inject a stale_hint rich message.

    The whole decision is encoded in this one function so callers (HTTP
    endpoint, future SSE handler) get consistent semantics. Args (now /
    threshold_days / dedup_hours) override settings only for tests.
    """
    now_utc = now or datetime.now(timezone.utc)
    threshold = threshold_days or settings.stale_days_threshold
    dedup = dedup_hours or settings.stale_dedup_hours

    last_completed = await _latest_completed_round(project_id, db)
    if not last_completed or not last_completed.completed_at:
        return StaleStatus(is_stale=False, days_ago=None, threshold_days=threshold)

    completed_at = _ensure_aware(last_completed.completed_at)
    days_ago = (now_utc - completed_at).days

    if days_ago < threshold:
        return StaleStatus(is_stale=False, days_ago=days_ago, threshold_days=threshold)

    session = await _active_session(project_id, db)

    suppressed_until = _read_dismissed_until(session) if session else None
    if suppressed_until and suppressed_until > now_utc:
        return StaleStatus(
            is_stale=False, days_ago=days_ago,
            threshold_days=threshold, suppressed_until=suppressed_until,
        )

    if session and _has_recent_stale_hint(
        session, now=now_utc, within=timedelta(hours=dedup),
    ):
        return StaleStatus(is_stale=True, days_ago=days_ago, threshold_days=threshold)

    injected = await inject_rich_message(
        db,
        rich_type="stale_hint",
        content=f"距上次检索 {days_ago} 天，文献库可能已过时",
        rich_data={
            "days_ago": days_ago,
            "threshold_days": threshold,
            "last_round_id": str(last_completed.id),
            "last_round_completed_at": completed_at.isoformat(),
        },
        project_id=project_id,
    )
    if injected:
        from app.services.telemetry import emit
        emit("stale_hint_impression",
             project_id=project_id, days_ago=days_ago, threshold=threshold)
    return StaleStatus(
        is_stale=True, days_ago=days_ago,
        threshold_days=threshold, just_injected=injected,
    )


async def dismiss_stale_hint(
    project_id: uuid.UUID,
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    days: Optional[int] = None,
) -> StaleStatus:
    """User clicked "先不用". Silence stale_hint for ``stale_dismiss_days``."""
    now_utc = now or datetime.now(timezone.utc)
    mute_days = days or settings.stale_dismiss_days
    until = now_utc + timedelta(days=mute_days)

    session = await _active_session(project_id, db)
    if session is None:
        return StaleStatus(
            is_stale=False, days_ago=None,
            threshold_days=settings.stale_days_threshold,
        )

    state_data = dict(session.state_data or {})
    state_data["stale_hint_dismissed_until"] = until.isoformat()
    session.state_data = state_data
    flag_modified(session, "state_data")
    await db.commit()

    from app.services.telemetry import emit
    emit("stale_hint_dismissed",
         project_id=project_id, mute_days=mute_days)

    return StaleStatus(
        is_stale=False, days_ago=None,
        threshold_days=settings.stale_days_threshold,
        suppressed_until=until,
    )


# ── Helpers ────────────────────────────────────────────────────────────────


async def _latest_completed_round(project_id: uuid.UUID, db: AsyncSession):
    SearchRound = _SearchRound()
    res = await db.execute(
        select(SearchRound)
        .where(
            SearchRound.project_id == project_id,
            SearchRound.completed_at.isnot(None),
        )
        .order_by(SearchRound.completed_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _active_session(project_id: uuid.UUID, db: AsyncSession):
    ConversationSession = _ConversationSession()
    res = await db.execute(
        select(ConversationSession)
        .where(
            ConversationSession.project_id == project_id,
            ConversationSession.is_active == True,  # noqa: E712
        )
        .order_by(ConversationSession.updated_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


def _has_recent_stale_hint(session, *, now: datetime, within: timedelta) -> bool:
    cutoff = now - within
    for msg in reversed(session.messages or []):
        if msg.get("rich_type") != "stale_hint":
            continue
        ts = _parse_ts(msg.get("timestamp"))
        if ts is None or ts >= cutoff:
            return True
    return False


def _read_dismissed_until(session) -> Optional[datetime]:
    raw = (session.state_data or {}).get("stale_hint_dismissed_until")
    if not raw:
        return None
    try:
        return _ensure_aware(datetime.fromisoformat(raw))
    except (TypeError, ValueError):
        logger.warning("[staleness] bad dismissed_until in session %s: %r",
                       session.id, raw)
        return None


def _parse_ts(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return _ensure_aware(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
