"""Tests for record_round.py CLI argument handling and dry-run path.

The actual recording path needs a real DB / API keys / project; we don't
exercise it here. But arg parsing and the dry-run code path are pure logic
and worth their own unit tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.parity import record_round


def test_parse_args_dry_run():
    ns = record_round.parse_args(["record_round", "--dry-run"])
    assert ns.dry_run is True
    assert ns.project_id is None
    assert ns.output is None


def test_parse_args_full():
    ns = record_round.parse_args([
        "record_round",
        "--project-id", "abc-123",
        "--output", "fixtures/golden.json",
    ])
    assert ns.project_id == "abc-123"
    assert isinstance(ns.output, Path)
    # Path may render with platform separator (\ on Windows, / on POSIX) —
    # compare via Path equality not str.
    assert ns.output == Path("fixtures/golden.json")
    assert ns.dry_run is False


def test_main_dry_run_returns_zero(capsys):
    rc = record_round.main(["record_round", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out


def test_main_missing_args_returns_error(capsys):
    rc = record_round.main(["record_round"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--project-id" in err
