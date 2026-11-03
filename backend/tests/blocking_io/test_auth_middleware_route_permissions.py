"""Regression anchor: route permission resolution must read the config off the loop.

``AuthMiddleware`` resolves the caller's route permissions for every
authenticated request. That reads the hot-reloaded authorization config through
``get_app_config()``, which stats and hashes ``config.yaml`` and
``extensions_config.json`` on every call and reparses them after an edit, so
calling it inline put that file IO on the event loop for every request.

The anchor drives the real middleware against real config files, with
authorization both disabled (the default) and enabled through the built-in RBAC
provider. The RBAC case returns a permission subset that only the file on disk
declares, so the read cannot be skipped without the assertion failing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from blockbuster import BlockingError
from fastapi import FastAPI, Request

import app.gateway.authz as authz
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import Permissions
from app.gateway.internal_auth import create_internal_auth_headers
from deerflow.config.app_config import reset_app_config
from deerflow.config.extensions_config import reset_extensions_config

pytestmark = pytest.mark.asyncio

_SANDBOX = "sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n"
_DISABLED = _SANDBOX + "authorization:\n  enabled: false\n"
_RBAC = (
    _SANDBOX
    + """authorization:
  enabled: true
  fail_closed: true
  default_role: user
  provider:
    use: deerflow.authz.rbac:RbacAuthorizationProvider
    config:
      roles:
        user:
          routes:
            allow: ["threads:read", "runs:read"]
"""
)


@pytest.fixture
def write_configs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    # Start from an empty route provider cache and restore it afterwards.
    monkeypatch.setattr(authz, "_route_provider_cache", {})
    monkeypatch.setattr(authz, "_route_provider_config_id", None)
    monkeypatch.setattr(authz, "_route_provider_config_sig", None)

    def write(config_yaml: str) -> None:
        config_path.write_text(config_yaml, encoding="utf-8")
        extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")

    reset_app_config()
    reset_extensions_config()
    yield write
    reset_app_config()
    reset_extensions_config()


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/probe")
    async def probe(request: Request) -> list[str]:
        return list(request.state.auth.permissions)

    return app


async def _permissions(client: httpx.AsyncClient) -> list[str]:
    response = await client.get("/api/probe", headers=create_internal_auth_headers())
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("config_yaml", "expected"),
    [
        pytest.param(_DISABLED, list(authz._ALL_PERMISSIONS), id="disabled"),
        pytest.param(_RBAC, [Permissions.THREADS_READ, Permissions.RUNS_READ], id="rbac"),
    ],
)
async def test_auth_middleware_reads_route_authorization_config_off_the_loop(write_configs, config_yaml: str, expected: list[str]) -> None:
    await asyncio.to_thread(write_configs, config_yaml)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        # The first request loads the config; the second only revalidates it,
        # which is the per-request cost.
        assert await _permissions(client) == expected
        assert await _permissions(client) == expected


async def test_blocking_probe_inline_route_config_read_actually_trips_the_gate(write_configs) -> None:
    """Meta-check: revalidating a loaded config inline on the loop is caught by the gate."""
    await asyncio.to_thread(write_configs, _RBAC)
    loaded = await asyncio.to_thread(authz._get_route_authorization_config)
    assert loaded.enabled is True

    with pytest.raises(BlockingError):
        authz._get_route_authorization_config()
