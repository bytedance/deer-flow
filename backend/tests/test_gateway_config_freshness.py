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

from app.gateway import deps as gateway_deps
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


def test_run_context_app_config_reflects_yaml_edit(tmp_path, monkeypatch):
    """``RunContext.app_config`` must follow live `config.yaml` edits.

    BUG-001 review feedback: the run-context that feeds worker / lead-agent
    factories must observe the same mtime reload that `get_config()` does;
    otherwise stale config slips back in through the run path even after the
    request dependency is fixed.
    """
    from unittest.mock import MagicMock

    from app.gateway.deps import get_run_context

    config_file = tmp_path / "config.yaml"
    _write_config_yaml(config_file, log_level="info")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_file))

    app = FastAPI()
    # Sentinel values for the rest of the RunContext wiring — we only care
    # about ``ctx.app_config`` for this assertion.
    app.state.checkpointer = MagicMock()
    app.state.store = MagicMock()
    app.state.run_event_store = MagicMock()
    app.state.run_events_config = {"frozen": "startup"}
    app.state.thread_store = MagicMock()

    @app.get("/run-ctx-log-level")
    def probe(ctx=Depends(get_run_context)):
        return {
            "log_level": ctx.app_config.log_level,
            "run_events_config": ctx.run_events_config,
        }

    client = TestClient(app)
    first = client.get("/run-ctx-log-level").json()
    assert first == {"log_level": "info", "run_events_config": {"frozen": "startup"}}

    _write_config_yaml(config_file, log_level="debug")
    future_mtime = config_file.stat().st_mtime + 5
    os.utime(config_file, (future_mtime, future_mtime))

    second = client.get("/run-ctx-log-level").json()
    # app_config follows the edit; run_events_config stays frozen to the
    # startup snapshot we wrote onto app.state above.
    assert second == {"log_level": "debug", "run_events_config": {"frozen": "startup"}}


@pytest.mark.parametrize(
    "exception",
    [
        FileNotFoundError("config.yaml not found"),
        PermissionError("config.yaml not readable"),
        ValueError("invalid config"),
        RuntimeError("yaml parse error"),
    ],
)
def test_get_config_returns_503_on_any_load_failure(monkeypatch, exception):
    """Any failure to materialise the config must surface as 503, not 500.

    Bytedance/deer-flow issue #3107 BUG-001 review: the original snapshot
    contract returned 503 when ``app.state.config is None``. The first cut of
    this fix only mapped ``FileNotFoundError`` to 503, which left
    ``PermissionError`` / ``yaml.YAMLError`` / ``ValidationError`` etc. bubbling
    up as 500. Catch every load failure at the request boundary.
    """

    def _broken_get_app_config():
        raise exception

    monkeypatch.setattr(gateway_deps, "get_app_config", _broken_get_app_config)

    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/probe")

    assert response.status_code == 503
    assert response.json() == {"detail": "Configuration not available"}
