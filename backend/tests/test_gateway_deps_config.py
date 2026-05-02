from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


def test_get_config_returns_app_state_config():
    """get_config should return the exact AppConfig stored on app.state."""
    app = FastAPI()
    config = AppConfig(sandbox=SandboxConfig(use="test"))
    app.state.config = config

    @app.get("/probe")
    def probe(cfg: AppConfig = Depends(get_config)):
        return {"same_identity": cfg is config, "log_level": cfg.log_level}

    client = TestClient(app)
    response = client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"same_identity": True, "log_level": "info"}


def test_get_config_reads_updated_app_state():
    """Swapping app.state.config should be visible to the dependency."""
    app = FastAPI()
    app.state.config = AppConfig(sandbox=SandboxConfig(use="test"), log_level="info")

    @app.get("/log-level")
    def log_level(cfg: AppConfig = Depends(get_config)):
        return {"level": cfg.log_level}

    client = TestClient(app)
    assert client.get("/log-level").json() == {"level": "info"}

    app.state.config = app.state.config.model_copy(update={"log_level": "debug"})
    assert client.get("/log-level").json() == {"level": "debug"}
