"""Regression tests for gateway config freshness on the request hot path.

Bytedance/deer-flow issue #3107 BUG-001: the worker and lead-agent path
captured ``app.state.config`` at gateway startup. ``config.yaml`` edits during
runtime were therefore ignored — ``get_app_config()``'s mtime-based reload
existed but was bypassed because the snapshot object was passed through
explicitly.

These tests pin the desired behaviour: a request-time ``get_config`` call must
observe the most recent on-disk ``config.yaml`` (mtime reload), and the
runtime ``ContextVar`` override must keep working for per-request injection.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from deerflow.config.app_config import (
    AppConfig,
    pop_current_app_config,
    push_current_app_config,
    reset_app_config,
    set_app_config,
)
from deerflow.config.sandbox_config import SandboxConfig


@pytest.fixture(autouse=True)
def _isolate_app_config_singleton():
    """Ensure each test starts with a clean module-level cache."""
    reset_app_config()
    yield
    reset_app_config()


def _write_config_yaml(path: Path, *, log_level: str) -> None:
    path.write_text(
        f"""
sandbox:
  use: deerflow.sandbox.local.provider:LocalSandboxProvider
log_level: {log_level}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(cfg: AppConfig = Depends(get_config)):
        return {"log_level": cfg.log_level}

    return app


def test_get_config_reflects_file_mtime_reload(tmp_path, monkeypatch):
    """Editing config.yaml at runtime must be visible to /probe without restart.

    This is the literal repro for the issue: the gateway must not freeze the
    config to whatever was on disk when the process started.
    """
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    app = _build_app()
    client = TestClient(app)
    assert client.get("/probe").json() == {"log_level": "info"}

    # Edit the file and bump its mtime — simulating a maintainer changing
    # max_tokens / model settings in production while the gateway is live.
    _write_config_yaml(config_file, log_level="debug")
    future_mtime = config_file.stat().st_mtime + 5
    os.utime(config_file, (future_mtime, future_mtime))

    assert client.get("/probe").json() == {"log_level": "debug"}


def test_get_config_respects_runtime_context_override(tmp_path, monkeypatch):
    """Per-request ``push_current_app_config`` injection must still win."""
    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    override = AppConfig(sandbox=SandboxConfig(use="test"), log_level="trace")
    push_current_app_config(override)
    try:
        app = _build_app()
        client = TestClient(app)
        assert client.get("/probe").json() == {"log_level": "trace"}
    finally:
        pop_current_app_config()


def test_get_config_respects_test_set_app_config():
    """``set_app_config`` (used by upload/skills router tests) keeps working."""
    injected = AppConfig(sandbox=SandboxConfig(use="test"), log_level="warning")
    set_app_config(injected)

    app = _build_app()
    client = TestClient(app)
    assert client.get("/probe").json() == {"log_level": "warning"}
