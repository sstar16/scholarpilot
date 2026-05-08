"""Tests for app/services/fetchers/types.py — exhaustiveness checks."""
from __future__ import annotations

import pytest

from app.services.fetchers.types import (
    ALL_SOURCE_IDS,
    CONDITIONAL_SOURCE_IDS,
    SourceId,
    assert_registry_exhaustive,
    is_valid_source_id,
)


def test_all_source_ids_non_empty():
    assert len(ALL_SOURCE_IDS) >= 16
    assert "openalex" in ALL_SOURCE_IDS
    assert "patenthub" in ALL_SOURCE_IDS
    assert "local_kb" in ALL_SOURCE_IDS


def test_conditional_source_ids_subset():
    # Anything we mark "conditional" must still be a known SourceId.
    assert CONDITIONAL_SOURCE_IDS.issubset(ALL_SOURCE_IDS)


def test_is_valid_source_id():
    assert is_valid_source_id("openalex") is True
    assert is_valid_source_id("crossref") is True
    assert is_valid_source_id("openalexx") is False
    assert is_valid_source_id("") is False


def test_assert_exhaustive_full_registry_passes():
    full = {sid: object() for sid in ALL_SOURCE_IDS}
    assert_registry_exhaustive(full)  # must not raise


def test_assert_exhaustive_missing_conditional_passes():
    # local_kb is conditional — its absence must NOT trigger the check.
    partial = {sid: object() for sid in ALL_SOURCE_IDS - CONDITIONAL_SOURCE_IDS}
    assert_registry_exhaustive(partial)  # must not raise


def test_assert_exhaustive_missing_required_raises():
    full = {sid: object() for sid in ALL_SOURCE_IDS}
    full.pop("openalex")
    with pytest.raises(RuntimeError, match="missing required source ids.*openalex"):
        assert_registry_exhaustive(full)


def test_assert_exhaustive_unknown_key_raises():
    full = {sid: object() for sid in ALL_SOURCE_IDS}
    full["typo_source"] = object()
    with pytest.raises(RuntimeError, match="unknown source ids.*typo_source"):
        assert_registry_exhaustive(full)


def test_source_id_literal_args():
    """SourceId Literal must contain only string literals; this catches a
    common refactoring mistake (e.g. accidentally including an int)."""
    from typing import get_args
    args = get_args(SourceId)
    assert all(isinstance(a, str) for a in args)
    assert len(args) == len(set(args)), "duplicate entries in SourceId"
