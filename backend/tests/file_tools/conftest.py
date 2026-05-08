"""Shared fixtures for file_tools tests (no DB / Redis / Celery dependencies)."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sandbox_dir(tmp_path: Path) -> Path:
    """Provide a temp base dir for PathSandbox tests."""
    base = tmp_path / "projects"
    base.mkdir()
    return base
