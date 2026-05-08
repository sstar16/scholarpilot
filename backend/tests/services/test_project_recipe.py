"""Tests for app/services/project_recipe.py — pure formatters + compute fns."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.project_recipe import (
    RecipeStats,
    compute_bucket_distribution,
    compute_keyword_signals,
    compute_source_hit_rate,
    compute_themes,
    format_recipe_markdown,
    regenerate_project_recipe,
)


_NOW = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)


# ── Pure formatter tests (no DB) ───────────────────────────────────────────


def test_format_empty_stats():
    md = format_recipe_markdown(RecipeStats(), now=_NOW)
    assert "项目食谱（自动生成 · 2026-04-27 12:00 UTC）" in md
    assert "还没有任何分类反馈" in md
    assert "暂无数据" in md
    assert "样本不足" in md


def test_format_full_stats():
    stats = RecipeStats(
        bucket_counts={
            "very_relevant": 12, "relevant": 18,
            "uncertain": 6, "irrelevant": 4,
        },
        total_classified=40,
        source_hit=[
            {"source": "openalex", "very_rel": 8, "total": 15, "hit_rate": 0.533},
            {"source": "crossref", "very_rel": 3, "total": 12, "hit_rate": 0.25},
        ],
        affinity_keywords=[("transformer", 8), ("attention", 7)],
        aversion_keywords=[("rule-based", 4), ("expert system", 3)],
        themes=[("transformer", 10), ("nlp", 8), ("attention", 7)],
    )
    md = format_recipe_markdown(stats, now=_NOW)
    # Bucket section
    assert "very_relevant: 12 篇 (30%)" in md
    assert "已分类总数：40 篇" in md
    # Source table
    assert "| openalex | 8/15 | 53% |" in md
    assert "| crossref | 3/12 | 25% |" in md
    # Keywords
    assert "transformer (8 次)" in md
    assert "rule-based (4 次)" in md
    # Themes
    assert "transformer · 10" in md
    # Directives — top 3 sources, top 5 affinity, top 5 aversion
    assert "优先信任来源 openalex, crossref" in md
    assert "扩展词优先选 transformer, attention" in md
    assert "避开 rule-based, expert system" in md
    assert "优先引用 very_relevant 桶" in md


def test_format_partial_no_aversion():
    """Affinity but no aversion → directives still emit affinity guidance."""
    stats = RecipeStats(
        bucket_counts={"very_relevant": 5, "relevant": 0, "uncertain": 0, "irrelevant": 0},
        total_classified=5,
        source_hit=[{"source": "arxiv", "very_rel": 5, "total": 5, "hit_rate": 1.0}],
        affinity_keywords=[("self-supervised", 3)],
        themes=[("self-supervised", 3)],
    )
    md = format_recipe_markdown(stats, now=_NOW)
    assert "暂无明显排斥模式" in md
    assert "优先信任来源 arxiv" in md
    assert "扩展词优先选 self-supervised" in md


# ── Compute function tests with FakeDB ─────────────────────────────────────


class _FakeDB:
    """Routes queries by table name found in compiled SQL.
    Each (table_name → rows) mapping yields scalar pairs."""

    def __init__(self, mapping: dict[str, list[Any]]):
        self._mapping = mapping
        self.commit = AsyncMock()

    async def execute(self, stmt):
        sql = str(stmt).lower()
        # Pick the first table name that matches
        rows: list[Any] = []
        for table, configured in self._mapping.items():
            if table in sql:
                rows = configured
                break
        result = MagicMock()
        result.all = MagicMock(return_value=rows)
        return result


@pytest.mark.asyncio
async def test_compute_bucket_distribution_aggregates():
    rows = [
        ("very_relevant", 12),
        ("relevant", 18),
        ("uncertain", 6),
        ("irrelevant", 4),
    ]
    db = _FakeDB({"document_classification": rows})
    counts, total = await compute_bucket_distribution(uuid.uuid4(), db)
    assert counts == {
        "very_relevant": 12, "relevant": 18, "uncertain": 6, "irrelevant": 4,
    }
    assert total == 40


@pytest.mark.asyncio
async def test_compute_bucket_distribution_partial():
    """Missing buckets should default to 0, not raise."""
    rows = [("very_relevant", 5)]
    db = _FakeDB({"document_classification": rows})
    counts, total = await compute_bucket_distribution(uuid.uuid4(), db)
    assert counts["very_relevant"] == 5
    assert counts["relevant"] == 0
    assert counts["irrelevant"] == 0
    assert total == 5


@pytest.mark.asyncio
async def test_compute_source_hit_rate_two_passes():
    """compute_source_hit_rate runs two SELECTs in fixed order:
    (1) very_relevant counts by source, (2) total counts by source."""

    responses = [
        [("openalex", 8), ("crossref", 3)],
        [("openalex", 15), ("crossref", 12), ("arxiv", 5)],
    ]

    class _SourceFakeDB:
        def __init__(self):
            self.commit = AsyncMock()
            self._idx = 0

        async def execute(self, _stmt):
            result = MagicMock()
            result.all = MagicMock(return_value=responses[self._idx])
            self._idx += 1
            return result

    db = _SourceFakeDB()
    rows = await compute_source_hit_rate(uuid.uuid4(), db)
    # Sorted by very_rel desc
    assert rows[0]["source"] == "openalex"
    assert rows[0]["very_rel"] == 8
    assert rows[0]["total"] == 15
    assert abs(rows[0]["hit_rate"] - 8/15) < 1e-6
    # arxiv has 0 very_rel and 5 total — should appear last
    arxiv = next(r for r in rows if r["source"] == "arxiv")
    assert arxiv["very_rel"] == 0
    assert arxiv["total"] == 5


@pytest.mark.asyncio
async def test_compute_keyword_signals_dedups_noise():
    """Tags appearing in BOTH very_relevant and irrelevant get dropped (noise)."""
    rows = [
        (["transformer", "neural-network"], "very_relevant"),
        (["transformer", "attention"], "very_relevant"),
        (["neural-network", "rule-based"], "irrelevant"),
        (["neural-network", "rule-based"], "irrelevant"),
    ]
    db = _FakeDB({"document_classification": rows})
    affinity, aversion = await compute_keyword_signals(uuid.uuid4(), db)
    aff_keys = {k for k, _ in affinity}
    av_keys = {k for k, _ in aversion}
    # transformer is purely positive
    assert "transformer" in aff_keys
    # rule-based is purely negative
    assert "rule-based" in av_keys
    # neural-network is in both (2 vs 2) → should be suppressed from both
    assert "neural-network" not in aff_keys
    assert "neural-network" not in av_keys


@pytest.mark.asyncio
async def test_compute_keyword_signals_normalises_case():
    rows = [
        (["Transformer", "ATTENTION"], "very_relevant"),
        (["transformer"], "very_relevant"),
    ]
    db = _FakeDB({"document_classification": rows})
    affinity, _ = await compute_keyword_signals(uuid.uuid4(), db)
    aff = dict(affinity)
    assert aff.get("transformer") == 2
    assert aff.get("attention") == 1


@pytest.mark.asyncio
async def test_compute_themes_top_n():
    rows = [
        (["alpha", "beta"],),
        (["alpha", "gamma"],),
        (["alpha"],),
        (["beta"],),
    ]
    db = _FakeDB({"document_classification": rows})
    themes = await compute_themes(uuid.uuid4(), db)
    assert themes[0] == ("alpha", 3)
    assert ("beta", 2) in themes
    assert ("gamma", 1) in themes


# ── Orchestrator integration ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_persists_recipe():
    """End-to-end: orchestrator runs 5 SELECTs + 1 UPDATE in known order:
    bucket_dist → source_hit_vr → source_hit_total → keyword_signals → themes
    → UPDATE user_profiles."""

    responses = [
        [("very_relevant", 5), ("relevant", 3)],            # bucket_dist
        [("openalex", 5)],                                   # source_hit very_rel
        [("openalex", 8)],                                   # source_hit total
        [(["transformer"], "very_relevant")],                # keyword_signals
        [(["transformer"], (3,))],                           # themes (single col)
    ]
    seen_updates = []

    class _OrchestrationDB:
        def __init__(self):
            self.commit = AsyncMock()
            self._idx = 0

        async def execute(self, stmt):
            sql = str(stmt).lower()
            if "update" in sql:
                seen_updates.append(stmt)
                return MagicMock()
            result = MagicMock()
            payload = responses[self._idx]
            # themes returns rows of single concept_tags column → ((tags,),)
            if self._idx == 4:
                payload = [(["transformer"],)]
            result.all = MagicMock(return_value=payload)
            self._idx += 1
            return result

    db = _OrchestrationDB()
    md, stats = await regenerate_project_recipe(
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        db=db,
        now=_NOW,
    )
    assert "项目食谱" in md
    assert "openalex" in md
    assert stats.bucket_counts["very_relevant"] == 5
    assert stats.total_classified == 8
    assert any(s["source"] == "openalex" for s in stats.source_hit)
    db.commit.assert_awaited()
    assert len(seen_updates) == 1


@pytest.mark.asyncio
async def test_regenerate_no_data_still_produces_recipe():
    """Project with zero classifications — recipe should still render gracefully."""

    class _EmptyDB:
        def __init__(self):
            self.commit = AsyncMock()

        async def execute(self, stmt):
            result = MagicMock()
            result.all = MagicMock(return_value=[])
            return result

    db = _EmptyDB()
    md, stats = await regenerate_project_recipe(
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        db=db,
        now=_NOW,
    )
    assert stats.total_classified == 0
    assert "还没有任何分类反馈" in md
    assert "样本不足" in md
