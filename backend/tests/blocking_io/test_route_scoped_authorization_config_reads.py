"""Regression anchors: route-scoped authorization must read the config off the loop.

The model, skill, suggestion and sandbox gates re-read the hot-reloaded
``authorization`` section through ``get_app_config()``, which stats and hashes
``config.yaml`` and ``extensions_config.json`` on every call and reparses them
after an edit. Async routes therefore call those synchronous helpers in a
worker, as ``/api/models/resolve`` already did.

Each case runs against real config files with the built-in RBAC provider and
asserts a decision only the policy on disk produces, so an anchor cannot pass
because the route stopped reading the config.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from blockbuster import BlockingError
from fastapi import FastAPI, Request

from app.gateway import authz
from app.gateway.routers import models, skills, suggestions
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config

pytestmark = pytest.mark.asyncio

_CONFIG_YAML = """sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
models:
  - name: allowed
    use: langchain_openai:ChatOpenAI
    model: allowed
  - name: restricted
    use: langchain_openai:ChatOpenAI
    model: restricted
authorization:
  enabled: true
  fail_closed: true
  default_role: user
  provider:
    use: deerflow.authz.rbac:RbacAuthorizationProvider
    config:
      roles:
        user:
          models:
            allow: ["allowed"]
          skills:
            allow: ["academic-paper-review"]
          sandbox:
            allow: false
"""

_USER = SimpleNamespace(id="user-123", system_role="user", oauth_provider=None, oauth_id=None)


def _write_configs(directory: Path) -> tuple[Path, Path]:
    config_path = directory / "config.yaml"
    extensions_path = directory / "extensions_config.json"
    config_path.write_text(_CONFIG_YAML, encoding="utf-8")
    extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    return config_path, extensions_path


@pytest_asyncio.fixture
async def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    config_path, extensions_path = await asyncio.to_thread(_write_configs, tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(authz, "_route_provider_cache", {})
    monkeypatch.setattr(authz, "_route_provider_config_id", None)
    monkeypatch.setattr(authz, "_route_provider_config_sig", None)
    reset_app_config()
    reset_extensions_config()
    # Load once off the loop: each request then pays only the per-call
    # revalidation, which is what every gated request carries.
    await asyncio.to_thread(get_app_config)

    application = FastAPI()

    @application.middleware("http")
    async def authenticate(request: Request, call_next):
        request.state.user = _USER
        request.state.auth_source = "session"
        request.state.auth = authz.AuthContext(_USER, ["threads:read"])
        return await call_next(request)

    application.state.thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    application.include_router(models.router)
    application.include_router(skills.router)
    application.include_router(suggestions.router)
    try:
        yield application
    finally:
        reset_app_config()
        reset_extensions_config()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway.test") as http_client:
        yield http_client


async def test_model_list_reads_authorization_off_the_loop(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/models")

    assert response.status_code == 200
    assert [model["name"] for model in response.json()["models"]] == ["allowed"]


async def test_model_details_read_authorization_off_the_loop(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/models/allowed")).status_code == 200
    assert (await client.get("/api/models/restricted")).status_code == 403


async def test_skill_list_reads_authorization_off_the_loop(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/skills")

    assert response.status_code == 200
    assert [skill["name"] for skill in response.json()["skills"]] == ["academic-paper-review"]


async def test_suggestions_read_model_authorization_off_the_loop(client: httpx.AsyncClient) -> None:
    # The denial comes before any model is created or invoked.
    response = await client.post(
        "/api/threads/thread-1/suggestions",
        json={"messages": [{"role": "user", "content": "Hello"}], "model_name": "restricted"},
    )

    assert response.status_code == 403


async def test_sandbox_gate_reads_authorization_off_the_loop(app: FastAPI) -> None:
    request = Request({"type": "http", "app": app, "headers": [], "state": {}})
    request.state.user = _USER
    request.state.auth_source = "session"
    sandbox_provider = MagicMock()

    lease = await authz.try_acquire_sandbox_for_request(
        request,
        sandbox_provider,
        "thread-1",
        user_id=_USER.id,
        app_config=await asyncio.to_thread(get_app_config),
    )

    assert lease.denied is True
    sandbox_provider.assert_not_called()


async def test_blocking_probe_inline_scoped_authorization_actually_trips_the_gate(app: FastAPI) -> None:
    """Meta-check: resolving the same authorization inline on the loop is caught."""
    with pytest.raises(BlockingError):
        authz.resolve_model_authorization(_USER, is_internal=False)
