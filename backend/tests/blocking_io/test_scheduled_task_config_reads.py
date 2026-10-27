"""Regression anchors: scheduled-task routes read the live config off the loop.

``get_config()`` routes through ``get_app_config()``, which stats and re-hashes
``config.yaml`` and ``extensions_config.json`` on every call and reparses them
after an edit (see ``config/AGENTS.md`` "Config Caching"). ``create_scheduled_task``
and ``update_scheduled_task`` read the ``scheduler`` section inline, so that
file IO ran on the event loop for every create/edit request — the same seam
#7557 fixed for route authorization and #7576 for the public auth routes.

The rest of this module already reads its own file work in a worker
(``load_agent_config``, ``_preview_cron`` and ``prepare_resume_updates`` all go
through ``asyncio.to_thread``), so these two calls were the remaining pair.

The strict Blockbuster gate from ``tests/blocking_io/conftest.py`` fails a test
whose body performs blocking IO on the loop, so an anchor cannot pass by
accident. Each test records where the config read ran and asserts it happened,
so a route that stopped reading config would fail rather than pass silently.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from blockbuster import BlockingError
from fastapi import HTTPException

from app.gateway.routers import scheduled_tasks as routes
from deerflow.config.app_config import get_app_config, reset_app_config

pytestmark = pytest.mark.asyncio

_CONFIG_YAML = """sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
scheduler:
  enabled: true
  poll_interval_seconds: 30
  recursion_limit: 88
"""


@pytest.fixture(autouse=True)
def _config_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(_CONFIG_YAML, encoding="utf-8")
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()


def _request() -> Any:
    request = MagicMock()
    request.app.state = MagicMock()
    return request


class _ConfigRecorder:
    """Counts config reads and records which threads performed them."""

    def __init__(self) -> None:
        self.calls = 0
        self.threads: list[int] = []

    def read(self):
        self.calls += 1
        self.threads.append(threading.get_ident())
        return get_app_config()


def _main_thread() -> int:
    """The thread the test body (and therefore the loop) runs on."""
    return threading.main_thread().ident or threading.get_ident()


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _ConfigRecorder:
    rec = _ConfigRecorder()
    monkeypatch.setattr(routes, "get_config", rec.read)
    # Stop each route immediately after it has read the config.
    monkeypatch.setattr(routes, "get_scheduled_task_repo", MagicMock(side_effect=HTTPException(status_code=499, detail="stop")))
    return rec


async def test_create_reads_the_scheduler_config_off_the_loop(recorder: _ConfigRecorder) -> None:
    with pytest.raises(HTTPException):
        await routes.create_scheduled_task(_request(), MagicMock())

    assert recorder.calls == 1, "the route must read the live config"
    assert recorder.threads[0] != _main_thread(), "the config read must run in a worker, not on the loop"


async def test_update_reads_the_scheduler_config_off_the_loop(recorder: _ConfigRecorder) -> None:
    with pytest.raises(HTTPException):
        await routes.update_scheduled_task("task-1", _request(), MagicMock())

    assert recorder.calls == 1, "the route must read the live config"
    assert recorder.threads[0] != _main_thread(), "the config read must run in a worker, not on the loop"


async def test_the_config_read_itself_is_what_trips_the_gate() -> None:
    """Meta-check: the same read called inline is caught by the strict gate.

    Without this, an anchor could pass because the route stopped reading the
    config at all rather than because the read moved to a worker.
    """
    await asyncio.to_thread(get_app_config)
    with pytest.raises(BlockingError):
        get_app_config()
