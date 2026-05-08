import pytest
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.project_scene import ProjectScene, resolve_scene
from app.models.project import Project
from app.models.search_round import SearchRound
from app.models.document import Document
from app.models.round_document import RoundDocument
from app.models.document_classification import DocumentClassification

pytestmark = pytest.mark.asyncio


async def _make_project(db: AsyncSession, user_id, current_round: int = 0) -> Project:
    p = Project(
        user_id=user_id,
        title="scene test project",
        description="",
        domain="computer_science",
        current_round=current_round,
    )
    db.add(p)
    await db.flush()
    await db.refresh(p)
    return p


async def test_scene_fresh_when_current_round_zero(db, test_user):
    project = await _make_project(db, test_user.id, current_round=0)
    scene = await resolve_scene(project.id, db)
    assert scene == ProjectScene.FRESH


async def test_scene_empty_when_round_runs_but_no_docs(db, test_user):
    project = await _make_project(db, test_user.id, current_round=1)
    scene = await resolve_scene(project.id, db)
    assert scene == ProjectScene.EMPTY_LIBRARY


async def test_scene_has_lib_via_round_document(db, test_user):
    project = await _make_project(db, test_user.id, current_round=1)
    round_obj = SearchRound(
        project_id=project.id,
        round_number=1,
        status="awaiting_feedback",
    )
    db.add(round_obj)
    doc = Document(
        source="arxiv",
        external_id=f"x{uuid.uuid4().hex[:6]}",
        doc_type="paper",
        title="t",
    )
    db.add(doc)
    await db.flush()
    db.add(RoundDocument(
        round_id=round_obj.id,
        document_id=doc.id,
    ))
    await db.flush()
    scene = await resolve_scene(project.id, db)
    assert scene == ProjectScene.HAS_LIBRARY


async def test_scene_has_lib_via_classification_only(db, test_user):
    """手动上传场景：只有 Classification 无 RoundDocument"""
    project = await _make_project(db, test_user.id, current_round=1)
    doc = Document(
        source="manual_upload",
        external_id=f"u{uuid.uuid4().hex[:6]}",
        doc_type="paper",
        title="t",
    )
    db.add(doc)
    await db.flush()
    db.add(DocumentClassification(
        user_id=test_user.id,
        project_id=project.id,
        document_id=doc.id,
        bucket="very_relevant",
        reason="",
    ))
    await db.flush()
    scene = await resolve_scene(project.id, db)
    assert scene == ProjectScene.HAS_LIBRARY
