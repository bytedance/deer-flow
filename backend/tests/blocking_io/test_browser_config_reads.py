"""Regression anchors: the browser config gates read the live config off the loop.

``_browser_tools_enabled`` calls ``get_app_config()``, which stats and re-hashes
``config.yaml`` and ``extensions_config.json`` on every call and reparses them
after an edit (see ``config/AGENTS.md`` "Config Caching"). The live-view
WebSocket runs that gate on every connect, and the navigate route on every
request, so the read must run in a worker — the same seam #7557 fixed for route
authorization.

The live socket also reads ``get_tool_config("browser_navigate")`` for the
session settings, which pays the same per-call cost.

The strict Blockbuster gate from ``tests/blocking_io/conftest.py`` fails a test
whose body blocks the loop, so an anchor cannot pass by accident.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.gateway.routers import browser as browser_router
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config

pytestmark = pytest.mark.asyncio

_CONFIG_YAML = """sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
tools:
  - name: browser_navigate
    group: browser
    use: deerflow.community.browser_automation.tools:browser_navigate_tool
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
    reset_extensions_config()


class _Recorder:
    """Counts config reads and records which threads performed them."""

    def __init__(self) -> None:
        self.calls = 0
        self.threads: list[int] = []

    def __call__(self):
        self.calls += 1
        self.threads.append(threading.get_ident())
        return get_app_config()


def _loop_thread() -> int:
    return threading.main_thread().ident or threading.get_ident()


async def test_capability_gate_reads_config_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(browser_router, "get_app_config", recorder, raising=False)
    # The gate imports get_app_config lazily inside the function body, so the
    # patch has to land on the module it imports from.
    import deerflow.config as config_module

    monkeypatch.setattr(config_module, "get_app_config", recorder)

    await browser_router._browser_tools_enabled_async()

    assert recorder.calls >= 1, "the gate must read the live config"
    assert recorder.threads[0] != _loop_thread(), "the config read must run in a worker, not on the loop"


async def test_the_gate_swallows_config_failures_without_leaving_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate suppresses config errors; that must not mask an on-loop read.

    ``_browser_tools_enabled`` wraps its read in ``contextlib.suppress(Exception)``
    so a broken config disables the surface instead of failing the request. A
    Blockbuster error raised on the loop would be swallowed too, which is why
    this module asserts the reading thread rather than relying on the gate
    raising: here the read still happens, in a worker, even when it fails.
    """
    recorder = _Recorder()
    import deerflow.config as config_module

    def _broken():
        recorder.calls += 1
        recorder.threads.append(threading.get_ident())
        raise ValueError("config unreadable")

    monkeypatch.setattr(config_module, "get_app_config", _broken)

    assert await browser_router._browser_tools_enabled_async() is False

    assert recorder.calls == 1
    assert recorder.threads[0] != _loop_thread(), "even a failing read must run in a worker"
