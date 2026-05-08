import pytest
import uuid
import io
from unittest.mock import patch
from app.main import app

pytestmark = pytest.mark.asyncio


def _override_auth(user):
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_overrides():
    app.dependency_overrides.clear()


async def _make_committed_project(db, test_user, current_round=1):
    from app.models.project import Project
    p = Project(
        user_id=test_user.id,
        title=f"import-test-{uuid.uuid4().hex[:6]}",
        description="", domain="cs", current_round=current_round,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_committed_session(db, test_user, project):
    from app.models.conversation_session import ConversationSession
    s = ConversationSession(
        user_id=test_user.id, project_id=project.id,
        current_state="idle", state_data={}, messages=[],
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_upload_returns_job_and_dispatches_celery(async_client, test_user, db):
    project = await _make_committed_project(db, test_user)
    session = await _make_committed_session(db, test_user, project)
    _override_auth(test_user)

    pdf_bytes = b"%PDF-1.4\n" + b"x" * 500  # valid size > 200B
    with patch("app.api.document_import.parse_pdf_metadata.delay") as mock_delay:
        try:
            files = {"file": ("sample.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
            resp = await async_client.post(
                f"/api/projects/{project.id}/documents/import-pdf",
                files=files,
                data={"session_id": str(session.id)},
            )
        finally:
            _clear_overrides()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "job_id" in body
    assert "document_id" in body
    assert body["status"] == "parsing"
    mock_delay.assert_called_once()


async def test_upload_rejects_non_pdf(async_client, test_user, db):
    project = await _make_committed_project(db, test_user)
    session = await _make_committed_session(db, test_user, project)
    _override_auth(test_user)

    try:
        files = {"file": ("oops.txt", io.BytesIO(b"hello"), "text/plain")}
        resp = await async_client.post(
            f"/api/projects/{project.id}/documents/import-pdf",
            files=files,
            data={"session_id": str(session.id)},
        )
    finally:
        _clear_overrides()

    assert resp.status_code in (400, 415)


async def test_confirm_updates_doc_and_dispatches_scoring(async_client, test_user, db):
    from app.models.document import Document
    from app.models.document_import_job import DocumentImportJob
    from datetime import datetime, timezone

    project = await _make_committed_project(db, test_user)
    session = await _make_committed_session(db, test_user, project)

    # Create placeholder doc + job in awaiting_edit
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    db.add(Document(
        id=doc_id, source="manual_upload",
        external_id=f"upload_{job_id.hex[:12]}",
        doc_type="paper", title="(解析中…)",
        import_source="manual_upload",
        imported_at=datetime.now(timezone.utc),
    ))
    db.add(DocumentImportJob(
        id=job_id, project_id=project.id, session_id=session.id,
        document_id=doc_id, user_id=test_user.id,
        original_filename="p.pdf", file_path="/tmp/fake.pdf",
        status="awaiting_edit",
    ))
    await db.commit()

    _override_auth(test_user)

    with patch("app.api.document_import.score_imported_document.delay") as mock_delay:
        try:
            resp = await async_client.put(
                f"/api/documents/{doc_id}/import-confirm",
                json={
                    "title": "Paper Confirmed",
                    "authors": ["A", "B"],
                    "year": 2024,
                    "abstract": "abs",
                    "one_line_summary": "主题",
                    "concept_tags": ["t1", "t2"],
                },
            )
        finally:
            _clear_overrides()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["next_status"] in ("scoring", "ready")
    mock_delay.assert_called_once_with(str(job_id))


async def test_cancel_cleans_file_and_deletes_placeholder_doc(async_client, test_user, db, tmp_path):
    from app.models.document import Document
    from app.models.document_import_job import DocumentImportJob
    from datetime import datetime, timezone

    project = await _make_committed_project(db, test_user)
    session = await _make_committed_session(db, test_user, project)

    pdf_path = tmp_path / "cancel.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    db.add(Document(
        id=doc_id, source="manual_upload",
        external_id=f"upload_{job_id.hex[:12]}",
        doc_type="paper", title="(解析中…)",
        import_source="manual_upload",
        imported_at=datetime.now(timezone.utc),
    ))
    db.add(DocumentImportJob(
        id=job_id, project_id=project.id, session_id=session.id,
        document_id=doc_id, user_id=test_user.id,
        original_filename="cancel.pdf", file_path=str(pdf_path),
        status="awaiting_edit",
    ))
    await db.commit()

    _override_auth(test_user)
    try:
        resp = await async_client.post(
            f"/api/documents/import-jobs/{job_id}/cancel",
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    assert not pdf_path.exists()


async def test_cancel_ready_job_is_idempotent(async_client, test_user, db, tmp_path):
    from app.models.document import Document
    from app.models.document_import_job import DocumentImportJob
    from datetime import datetime, timezone

    project = await _make_committed_project(db, test_user)
    session = await _make_committed_session(db, test_user, project)

    pdf_path = tmp_path / "done.pdf"
    pdf_path.write_bytes(b"%PDF")

    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()
    db.add(Document(
        id=doc_id, source="manual_upload",
        external_id=f"upload_{job_id.hex[:12]}",
        doc_type="paper", title="Done Doc",
        import_source="manual_upload",
        imported_at=datetime.now(timezone.utc),
    ))
    db.add(DocumentImportJob(
        id=job_id, project_id=project.id, session_id=session.id,
        document_id=doc_id, user_id=test_user.id,
        original_filename="done.pdf", file_path=str(pdf_path),
        status="ready",
    ))
    await db.commit()

    _override_auth(test_user)
    try:
        resp = await async_client.post(
            f"/api/documents/import-jobs/{job_id}/cancel",
        )
    finally:
        _clear_overrides()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    # file should NOT be deleted for terminal job
    assert pdf_path.exists()
