import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from app.workers.import_tasks import _parse_pdf_metadata_async

pytestmark = pytest.mark.asyncio


def _fake_db_context(mock_db):
    """Return an async context manager yielding the mock db."""
    @asynccontextmanager
    async def _cm():
        yield mock_db
    return _cm()


async def test_parse_happy_path_sets_awaiting_edit(tmp_path):
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-fake")

    job_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    session_id = uuid.uuid4()

    mock_job = MagicMock(
        id=job_id, document_id=doc_id, session_id=session_id,
        original_filename="sample.pdf", file_path=str(pdf_file),
        status="parsing", failure_reason=None, metadata_draft=None,
    )
    mock_doc = MagicMock(id=doc_id, one_line_summary=None)

    async def fake_get(model, key):
        name = model.__name__
        if "ImportJob" in name:
            return mock_job
        if "Document" in name:
            return mock_doc
        return None

    mock_db = MagicMock()
    mock_db.get = AsyncMock(side_effect=fake_get)
    mock_db.commit = AsyncMock()

    with patch("app.workers.import_tasks.fitz.open") as mock_open:
        mock_pdf = MagicMock()
        page1 = MagicMock()
        page1.get_text.return_value = "Title: Paper X\nAuthors: A, B"
        page2 = MagicMock()
        page2.get_text.return_value = "Abstract..."
        page3 = MagicMock()
        page3.get_text.return_value = "more"
        mock_pdf.__len__ = MagicMock(return_value=3)
        mock_pdf.pages.return_value = [page1, page2, page3]
        mock_open.return_value.__enter__.return_value = mock_pdf

        with patch("app.workers.import_tasks.DocImportAgent") as MockAgent:
            inst = MockAgent.return_value
            fake_meta = MagicMock(
                title="Paper X", title_zh=None, authors=["A", "B"],
                year=2024, abstract="x", doi=None, journal=None,
                one_line_summary="一句话", concept_tags=["t1", "t2"],
            )
            inst.extract = AsyncMock(return_value=fake_meta)

            with patch("app.workers.import_tasks.get_llm_manager", new=AsyncMock(return_value=MagicMock())):
                with patch("app.workers.import_tasks.inject_rich_message", new=AsyncMock()) as mock_push:
                    with patch("app.workers.import_tasks._get_db", return_value=_fake_db_context(mock_db)):
                        await _parse_pdf_metadata_async(str(job_id))

    assert mock_job.status == "awaiting_edit"
    assert mock_job.metadata_draft is not None
    assert mock_doc.title == "Paper X"
    mock_push.assert_awaited()


async def test_parse_bad_pdf_sets_failed(tmp_path):
    pdf_file = tmp_path / "bad.pdf"
    pdf_file.write_bytes(b"garbage")

    job_id = uuid.uuid4()
    mock_job = MagicMock(
        id=job_id, document_id=uuid.uuid4(), session_id=uuid.uuid4(),
        original_filename="bad.pdf", file_path=str(pdf_file),
        status="parsing", failure_reason=None,
    )
    mock_doc = MagicMock()

    async def fake_get(model, key):
        name = model.__name__
        if "ImportJob" in name:
            return mock_job
        return mock_doc

    mock_db = MagicMock()
    mock_db.get = AsyncMock(side_effect=fake_get)
    mock_db.commit = AsyncMock()

    with patch("app.workers.import_tasks.fitz.open", side_effect=Exception("corrupt pdf")):
        with patch("app.workers.import_tasks.inject_rich_message", new=AsyncMock()):
            with patch("app.workers.import_tasks._get_db", return_value=_fake_db_context(mock_db)):
                await _parse_pdf_metadata_async(str(job_id))

    assert mock_job.status == "failed"
    assert "corrupt" in (mock_job.failure_reason or "").lower()


async def test_score_happy_path_runs_scoring_and_writes_md():
    from app.workers.import_tasks import _score_imported_document_async

    job_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    project_id = uuid.uuid4()
    session_id = uuid.uuid4()

    mock_job = MagicMock(
        id=job_id, document_id=doc_id, project_id=project_id,
        user_id=uuid.uuid4(), session_id=session_id,
        original_filename="p.pdf", status="scoring", failure_reason=None,
    )
    mock_doc = MagicMock(
        id=doc_id, title="Paper", title_zh=None, authors="A",
        source="manual_upload", external_id="upload_abc", doi=None,
        journal=None, publication_date=None, url=None, pdf_url=None,
        abstract="abs", ai_summary=None, ai_key_points=None,
        one_line_summary="yyyy", quality_score=None,
        fulltext_text=None, concept_tags=["t1"],
        ai_summary_source="not_generated",
    )
    # current_round > 0 → HAS_LIBRARY (not FRESH)
    mock_project = MagicMock(id=project_id, current_round=2, title="Proj")

    async def fake_get(model, key):
        name = model.__name__
        if "ImportJob" in name:
            return mock_job
        if "Document" in name:
            return mock_doc
        if "Project" in name:
            return mock_project
        return None

    mock_db = MagicMock()
    mock_db.get = AsyncMock(side_effect=fake_get)
    mock_db.commit = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=lambda: None
    ))

    scoring_result = MagicMock(
        agent_score=7.5, rationale="摘要", one_line_summary="abc",
        scoring_failed=False,
    )

    with patch("app.workers.import_tasks.ScoringAgent") as MockScoring:
        MockScoring.return_value.score_single = AsyncMock(return_value=scoring_result)
        with patch("app.workers.import_tasks.LiteratureWriter") as MockWriter:
            MockWriter.return_value.persist = AsyncMock(return_value="slug_abc")
            with patch("app.workers.import_tasks.tool_registry", return_value=MagicMock()):
                with patch("app.workers.import_tasks.get_llm_manager", new=AsyncMock(return_value=MagicMock())):
                    with patch("app.workers.import_tasks.inject_rich_message", new=AsyncMock()) as mock_push:
                        with patch("app.workers.import_tasks._get_db", return_value=_fake_db_context(mock_db)):
                            await _score_imported_document_async(str(job_id))

    assert mock_doc.quality_score == 7.5
    assert mock_job.status == "ready"
    MockWriter.return_value.persist.assert_awaited()
    mock_push.assert_awaited()


async def test_score_fresh_scene_skips_scoring():
    from app.workers.import_tasks import _score_imported_document_async

    job_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    project_id = uuid.uuid4()

    mock_job = MagicMock(
        id=job_id, document_id=doc_id, project_id=project_id,
        user_id=uuid.uuid4(), session_id=uuid.uuid4(),
        original_filename="p.pdf", status="scoring",
    )
    mock_doc = MagicMock(
        id=doc_id, title="X", title_zh=None, authors="A",
        source="manual_upload", external_id="upload_z", doi=None,
        journal=None, publication_date=None, url=None, pdf_url=None,
        abstract=None, ai_summary=None, ai_key_points=None,
        one_line_summary="z", quality_score=None,
        fulltext_text=None, concept_tags=[],
        ai_summary_source="not_generated",
    )
    mock_project = MagicMock(id=project_id, current_round=0, title="Fresh")  # FRESH

    async def fake_get(model, key):
        name = model.__name__
        if "ImportJob" in name:
            return mock_job
        if "Document" in name:
            return mock_doc
        if "Project" in name:
            return mock_project
        return None

    mock_db = MagicMock()
    mock_db.get = AsyncMock(side_effect=fake_get)
    mock_db.commit = AsyncMock()

    with patch("app.workers.import_tasks.ScoringAgent") as MockScoring:
        with patch("app.workers.import_tasks.LiteratureWriter") as MockWriter:
            MockWriter.return_value.persist = AsyncMock(return_value="slug_x")
            with patch("app.workers.import_tasks.tool_registry", return_value=MagicMock()):
                with patch("app.workers.import_tasks.get_llm_manager", new=AsyncMock(return_value=MagicMock())):
                    with patch("app.workers.import_tasks.inject_rich_message", new=AsyncMock()) as mock_push:
                        with patch("app.workers.import_tasks._get_db", return_value=_fake_db_context(mock_db)):
                            await _score_imported_document_async(str(job_id))

    # Scoring agent NOT called
    MockScoring.assert_not_called()
    assert mock_job.status == "ready"
    # FinalCard rich_message should have evaluation_skipped=True
    push_call = mock_push.await_args
    rich_data = push_call.kwargs.get("rich_data", {})
    assert rich_data.get("evaluation_skipped") is True
