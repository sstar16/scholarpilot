import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.workers.cleanup_tasks import _cleanup_async
from app.models.search_round import SearchRound
from app.models.project import Project


@pytest.mark.asyncio
async def test_cleanup_deletes_expired_rounds(db: AsyncSession, test_user):
    """expires_at < now 的 round 被删，未过期的保留。"""
    project = Project(user_id=test_user.id, title='测试', description='', domain='cs', domains=['cs'])
    db.add(project)
    await db.commit()
    await db.refresh(project)

    now = datetime.now(timezone.utc)
    expired = SearchRound(
        project_id=project.id, round_number=1, status='complete',
        expires_at=now - timedelta(hours=1),
    )
    not_expired = SearchRound(
        project_id=project.id, round_number=2, status='complete',
        expires_at=now + timedelta(days=7),
    )
    no_ttl = SearchRound(
        project_id=project.id, round_number=3, status='awaiting_keywords',
        expires_at=None,
    )
    db.add_all([expired, not_expired, no_ttl])
    await db.commit()

    result = await _cleanup_async(db)
    assert result['deleted'] == 1

    remaining = (await db.execute(select(SearchRound.id))).all()
    remaining_ids = {row[0] for row in remaining}
    assert not_expired.id in remaining_ids
    assert no_ttl.id in remaining_ids
    assert expired.id not in remaining_ids


@pytest.mark.asyncio
async def test_cleanup_idempotent_when_no_expired(db: AsyncSession, test_user):
    project = Project(user_id=test_user.id, title='t', description='', domain='cs', domains=['cs'])
    db.add(project)
    await db.commit()
    result = await _cleanup_async(db)
    assert result['deleted'] == 0
