"""Tests for the recipe_tasks Redis dedup lock."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


# Stub out app.workers.celery_app and app.workers.search_tasks before import.
class _FakeCeleryApp:
    def task(self, **_kw):
        def deco(f):
            return f
        return deco


_celery_stub = types.ModuleType("app.workers.celery_app")
_celery_stub.app = _FakeCeleryApp()
sys.modules.setdefault("app.workers.celery_app", _celery_stub)

_search_stub = types.ModuleType("app.workers.search_tasks")
_search_stub._run_async = lambda coro: None
sys.modules.setdefault("app.workers.search_tasks", _search_stub)

# Stub redis if not configured (tests don't need real Redis)
_redis_stub_state = {"keys": {}}


class _FakeRedisClient:
    """Minimal Redis impl: SET ... NX EX honored. ``reset()`` clears state."""

    def set(self, key, value, nx=False, ex=None):
        if nx and key in _redis_stub_state["keys"]:
            return None
        _redis_stub_state["keys"][key] = value
        return True


_real_redis_module = types.ModuleType("redis")
_real_redis_module.Redis = MagicMock()
_real_redis_module.Redis.from_url = MagicMock(return_value=_FakeRedisClient())
sys.modules["redis"] = _real_redis_module


from app.workers import recipe_tasks  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_redis_state():
    _redis_stub_state["keys"].clear()
    yield


def test_first_call_acquires_lock_runs_task(monkeypatch):
    """First call: lock acquired, task body runs."""
    ran = []
    monkeypatch.setattr(
        recipe_tasks, "_run_async",
        lambda coro: ran.append("ran") or {"status": "ok"},
    )
    out = recipe_tasks.regenerate_project_recipe_task(
        None, "11111111-1111-1111-1111-111111111111", "user-1",
    )
    assert ran == ["ran"]
    assert out == {"status": "ok"}


def test_second_call_within_window_dedupes(monkeypatch):
    """Second call within 60s: lock held → returns deduped, body NOT run."""
    ran = []
    monkeypatch.setattr(
        recipe_tasks, "_run_async",
        lambda coro: ran.append("ran") or {"status": "ok"},
    )
    pid = "11111111-1111-1111-1111-111111111111"
    recipe_tasks.regenerate_project_recipe_task(None, pid, "user-1")
    out = recipe_tasks.regenerate_project_recipe_task(None, pid, "user-1")
    assert ran == ["ran"]  # body ran exactly once
    assert out == {"status": "deduped"}


def test_different_projects_dont_share_lock(monkeypatch):
    """Two distinct projects → both run independently."""
    ran = []
    monkeypatch.setattr(
        recipe_tasks, "_run_async",
        lambda coro: ran.append("ran") or {"status": "ok"},
    )
    recipe_tasks.regenerate_project_recipe_task(
        None, "11111111-1111-1111-1111-111111111111", "u1",
    )
    recipe_tasks.regenerate_project_recipe_task(
        None, "22222222-2222-2222-2222-222222222222", "u1",
    )
    assert ran == ["ran", "ran"]


def test_redis_failure_falls_through_to_run(monkeypatch):
    """Redis outage shouldn't cause silently-dropped regenerations."""
    ran = []
    monkeypatch.setattr(
        recipe_tasks, "_run_async",
        lambda coro: ran.append("ran") or {"status": "ok"},
    )

    def _broken_acquire(_pid):
        raise ConnectionError("redis down")

    # Patch the from_url to raise so the helper's except branch fires.
    fake_redis_module = sys.modules["redis"]
    monkeypatch.setattr(
        fake_redis_module.Redis, "from_url",
        MagicMock(side_effect=ConnectionError("redis down")),
    )
    out = recipe_tasks.regenerate_project_recipe_task(
        None, "33333333-3333-3333-3333-333333333333", "u1",
    )
    assert ran == ["ran"], "Redis failure must not prevent task body from running"
    assert out == {"status": "ok"}


def test_task_body_exception_returns_failed_status(monkeypatch):
    """If the inner _run_async raises, return {status: failed} not crash."""

    def _raises(_coro):
        raise RuntimeError("db down")

    monkeypatch.setattr(recipe_tasks, "_run_async", _raises)
    out = recipe_tasks.regenerate_project_recipe_task(
        None, "44444444-4444-4444-4444-444444444444", "u1",
    )
    assert out["status"] == "failed"
    assert "db down" in out["error"]
