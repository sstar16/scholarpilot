"""Tests for RelationStore (SQLite relation graph)."""

from __future__ import annotations

import pytest

from backend.app.knowledge_base.relations import RelationStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db = RelationStore(tmp_path / "relations.db")
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def sample_citations():
    return [("W0", "W1"), ("W0", "W2"), ("W1", "W2"), ("W1", "W3"), ("W3", "W0")]


@pytest.fixture
def sample_topics():
    return [
        ("W0", "T1", 0.9),
        ("W0", "T2", 0.5),
        ("W1", "T1", 0.8),
        ("W2", "T2", 0.7),
        ("W2", "T3", 0.6),
        ("W3", "T1", 0.95),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_schema(tmp_path):
    db = RelationStore(tmp_path / "schema_test.db")
    db.init_schema()
    # Tables should exist — querying them must not raise.
    db.conn.execute("SELECT * FROM citations").fetchall()
    db.conn.execute("SELECT * FROM work_topics").fetchall()
    db.conn.execute("SELECT * FROM coauthorship").fetchall()
    db.close()


def test_insert_citations(store, sample_citations):
    store.bulk_insert_citations(sample_citations)
    assert store.citation_count() == 5


def test_get_cited_by(store, sample_citations):
    store.bulk_insert_citations(sample_citations)
    cited_by_w2 = set(store.get_cited_by("W2"))
    assert cited_by_w2 == {"W0", "W1"}


def test_get_references(store, sample_citations):
    store.bulk_insert_citations(sample_citations)
    refs_w0 = set(store.get_references("W0"))
    assert refs_w0 == {"W1", "W2"}


def test_expand_by_citation(store, sample_citations):
    store.bulk_insert_citations(sample_citations)
    expanded = set(store.expand_by_citation(["W0"], hops=1))
    # W0 cites W1, W2; W3 cites W0 — all three should be discovered.
    assert {"W1", "W2", "W3"} == expanded


def test_same_topic_works(store, sample_citations, sample_topics):
    store.bulk_insert_citations(sample_citations)
    store.bulk_insert_topics(sample_topics)
    # W0 has T1, T2.  T1 → W1, W3.  T2 → W2.
    same = set(store.get_same_topic_works("W0"))
    assert same == {"W1", "W2", "W3"}
