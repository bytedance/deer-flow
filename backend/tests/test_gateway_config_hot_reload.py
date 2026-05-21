"""End-to-end regression for #3112 — gateway config hot reload.

Validates that ``get_config`` and ``get_run_context`` both reflect a live
``config.yaml`` edit on the next request, without restarting the
gateway process. The test exercises the same chain that broke before the
fix:

    config.yaml mtime changes
        → deerflow.config.get_app_config() reloads (mtime-based)
        → app.gateway.deps.get_config(request) returns the new instance
        → app.gateway.deps.get_run_context(request).app_config is the new instance

If any link reverts to a startup-time snapshot, the second request below
will see the old ``log_level`` / ``model.max_tokens`` and the assertion
fails.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config, get_run_context
from deerflow.config import app_config as app_config_module
from deerflow.config.app_config import AppConfig


def _write_config(path: Path, *, log_level: str, max_tokens: int) -> None:
    payload = {
        "log_level": log_level,
        "models": [
            {
                "name": "test-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-4o-mini",
                "max_tokens": max_tokens,
            }
        ],
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


@pytest.fixture
def hot_reload_config(tmp_path, monkeypatch):
    """Write a temporary config.yaml and point AppConfig resolution at it.

    Resets the AppConfig singleton before and after the test so the
    cached state of other tests does not leak.
    """
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, log_level="info", max_tokens=8192)

    # Force AppConfig.resolve_config_path() to return our temp file.
    monkeypatch.setattr(AppConfig, "resolve_config_path", classmethod(lambda cls, p=None: config_path))

    # Clear any AppConfig singleton populated by an earlier test.
    app_config_module.reset_app_config()
    yield config_path
    app_config_module.reset_app_config()


def test_get_config_reflects_yaml_edit(hot_reload_config):
    """Editing config.yaml must change the next ``Depends(get_config)`` result."""
    app = FastAPI()

    @app.get("/log-level")
    def log_level(cfg: AppConfig = Depends(get_config)):
        return {"level": cfg.log_level}

    @app.get("/max-tokens")
    def max_tokens(cfg: AppConfig = Depends(get_config)):
        model = cfg.get_model_config("test-model")
        return {"max_tokens": getattr(model, "max_tokens", None)}

    client = TestClient(app)

    assert client.get("/log-level").json() == {"level": "info"}
    assert client.get("/max-tokens").json() == {"max_tokens": 8192}

    # Bump mtime so AppConfig's mtime-based reload triggers. ``time.sleep``
    # is necessary because some filesystems only honour second-level mtime
    # resolution; touching twice in the same second would be a no-op.
    time.sleep(1.1)
    _write_config(hot_reload_config, log_level="debug", max_tokens=384000)

    assert client.get("/log-level").json() == {"level": "debug"}
    assert client.get("/max-tokens").json() == {"max_tokens": 384000}


def test_get_run_context_app_config_reflects_yaml_edit(hot_reload_config):
    """``RunContext.app_config`` must follow the live AppConfig too.

    This is the path the agent worker uses; without it the lead-agent
    factory and SummarizationMiddleware would receive a stale snapshot
    even after ``get_config`` was fixed.
    """
    app = FastAPI()

    # ``get_run_context`` requires several other singletons (checkpointer,
    # store, etc.) on app.state. Stub them with sentinel objects so the
    # dependency wiring runs to completion; the assertions below only
    # care about ``ctx.app_config``.
    sentinel = object()
    app.state.checkpointer = sentinel
    app.state.store = sentinel
    app.state.run_event_store = sentinel
    app.state.thread_store = sentinel

    @app.get("/run-context-max-tokens")
    def probe(ctx=Depends(get_run_context)):
        model = ctx.app_config.get_model_config("test-model")
        return {"max_tokens": getattr(model, "max_tokens", None)}

    client = TestClient(app)
    assert client.get("/run-context-max-tokens").json() == {"max_tokens": 8192}

    time.sleep(1.1)
    _write_config(hot_reload_config, log_level="info", max_tokens=384000)

    assert client.get("/run-context-max-tokens").json() == {"max_tokens": 384000}
