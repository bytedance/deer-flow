"""Regression tests for ``app.gateway.deps.get_config``.

These tests verify that ``get_config`` returns the live ``AppConfig``
resolved through ``deerflow.config.get_app_config`` rather than a
startup-time snapshot stored on ``app.state``. This is the contract
required to fix issue #3112: edits to ``config.yaml`` must take effect
on the next request without a process restart.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


def test_get_config_returns_live_app_config(monkeypatch):
    """``get_config`` should return whatever ``get_app_config()`` resolves to."""
    config = AppConfig(sandbox=SandboxConfig(use="test"))
    monkeypatch.setattr("app.gateway.deps.get_app_config", lambda: config)

    app = FastAPI()

    @app.get("/probe")
    def probe(cfg: AppConfig = Depends(get_config)):
        return {"same_identity": cfg is config, "log_level": cfg.log_level}

    client = TestClient(app)
    response = client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"same_identity": True, "log_level": "info"}


def test_get_config_picks_up_reload(monkeypatch):
    """A subsequent ``get_app_config()`` reload must be visible to the dependency.

    This is the regression for #3112: if ``get_config`` cached the first
    AppConfig instance, edits to ``config.yaml`` would never reach
    routers nor the run path.
    """
    initial = AppConfig(sandbox=SandboxConfig(use="test"), log_level="info")
    reloaded = AppConfig(sandbox=SandboxConfig(use="test"), log_level="debug")

    state = {"current": initial}
    monkeypatch.setattr("app.gateway.deps.get_app_config", lambda: state["current"])

    app = FastAPI()

    @app.get("/log-level")
    def log_level(cfg: AppConfig = Depends(get_config)):
        return {"level": cfg.log_level}

    client = TestClient(app)
    assert client.get("/log-level").json() == {"level": "info"}

    # Simulate ``get_app_config()`` reloading after an mtime change.
    state["current"] = reloaded
    assert client.get("/log-level").json() == {"level": "debug"}


def test_get_config_503_when_config_unavailable(monkeypatch):
    """If config loading fails, surface a 503 rather than a 500."""

    def _raise():
        raise FileNotFoundError("config.yaml not found")

    monkeypatch.setattr("app.gateway.deps.get_app_config", _raise)

    app = FastAPI()

    @app.get("/probe")
    def probe(cfg: AppConfig = Depends(get_config)):  # pragma: no cover - unreachable
        return cfg.log_level

    client = TestClient(app)
    response = client.get("/probe")
    assert response.status_code == 503
    assert response.json() == {"detail": "Configuration not available"}
