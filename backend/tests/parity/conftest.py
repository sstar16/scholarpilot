"""Parity test conftest: --update-golden flag, golden-fixture root path."""
from __future__ import annotations

from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="When set, parity tests overwrite golden fixtures with the "
             "current run's output instead of failing on drift.",
    )


@pytest.fixture
def update_golden(request) -> bool:
    return request.config.getoption("--update-golden")


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
