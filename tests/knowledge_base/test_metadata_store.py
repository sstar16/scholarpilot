"""
Tests for MetadataStore (DuckDB-backed).

Fixtures: tmp_kb_dir, sample_works — defined in conftest.py
"""
import pytest
from pathlib import Path

from backend.app.knowledge_base.metadata_store import MetadataStore


@pytest.fixture
def store(tmp_kb_dir):
    """Initialised MetadataStore backed by a temp DuckDB file."""
    ms = MetadataStore(tmp_kb_dir / "metadata.duckdb")
    ms.init_schema()
    yield ms
    ms.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_create_schema(store):
    """After init_schema the table exists and is empty."""
    assert store.count() == 0


# ---------------------------------------------------------------------------
# Bulk insert
# ---------------------------------------------------------------------------

def test_bulk_insert(store, sample_works):
    """Inserting 100 distinct works persists all rows."""
    store.bulk_insert(sample_works)
    assert store.count() == 100


def test_bulk_insert_dedup(store, sample_works):
    """Inserting the same records twice keeps exactly 100 rows (INSERT OR REPLACE)."""
    store.bulk_insert(sample_works)
    store.bulk_insert(sample_works)
    assert store.count() == 100


# ---------------------------------------------------------------------------
# get_by_ids
# ---------------------------------------------------------------------------

def test_query_by_ids(store, sample_works):
    """get_by_ids returns matches only; non-existing ids are silently ignored."""
    store.bulk_insert(sample_works)
    # W1000000 and W1000001 exist; W9999999 does not
    results = store.get_by_ids(["W1000000", "W1000001", "W9999999"])
    assert len(results) == 2
    returned_ids = {r["openalex_id"] for r in results}
    assert returned_ids == {"W1000000", "W1000001"}


# ---------------------------------------------------------------------------
# query (filtered)
# ---------------------------------------------------------------------------

def test_query_by_year_range(store, sample_works):
    """query with year_from/year_to returns only works in that range."""
    store.bulk_insert(sample_works)
    results = store.query(year_from=2024, year_to=2025)
    assert len(results) > 0
    for r in results:
        assert 2024 <= r["publication_year"] <= 2025


def test_query_by_topic(store, sample_works):
    """query with topic_id returns only works with that topic."""
    store.bulk_insert(sample_works)
    results = store.query(topic_id="T0")
    assert len(results) > 0
    for r in results:
        assert r["primary_topic_id"] == "T0"


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def test_stats(store, sample_works):
    """stats() returns expected top-level keys with correct total."""
    store.bulk_insert(sample_works)
    s = store.stats()
    assert "total_works" in s
    assert "by_year" in s
    assert "by_language" in s
    assert s["total_works"] == 100
    assert isinstance(s["by_year"], list)
    assert isinstance(s["by_language"], list)
    # by_year entries must have publication_year and count keys
    for entry in s["by_year"]:
        assert "publication_year" in entry
        assert "count" in entry
    # by_language entries must have language and count keys
    for entry in s["by_language"]:
        assert "language" in entry
        assert "count" in entry
