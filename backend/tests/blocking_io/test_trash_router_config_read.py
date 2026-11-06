"""Trash listing must resolve its destructive retention policy off the loop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from blockbuster import BlockingError
from fastapi import FastAPI

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import trash
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    def write_configs():
        config_path = tmp_path / "config.yaml"
        config_path.write_text("sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\nprojects:\n  trash_retention_days: 365\n", encoding="utf-8")
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
        return config_path, extensions_path

    config_path, extensions_path = await asyncio.to_thread(write_configs)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    reset_app_config()
    reset_extensions_config()
    await asyncio.to_thread(get_app_config)

    repo = AsyncMock()
    repo.list_trashed.return_value = []
    repo.count_trashed.return_value = 0
    sweep = AsyncMock()
    monkeypatch.setattr(trash, "run_trash_retention_sweep", sweep)
    monkeypatch.setattr(trash, "get_paths", lambda: object())
    monkeypatch.setattr(trash, "_LAST_RECONCILIATION", {})
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.project_document_repo = repo
    app.include_router(trash.router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway.test") as http_client:
            yield http_client, sweep
    finally:
        reset_app_config()
        reset_extensions_config()


async def test_trash_listing_reads_configured_retention_off_the_loop(client):
    http_client, sweep = client

    response = await http_client.get("/api/trash/documents")

    assert response.status_code == 200
    sweep.assert_awaited_once()
    assert sweep.await_args.kwargs["retention_days"] == 365


async def test_inline_config_probe_trips_the_blocking_gate(client):
    with pytest.raises(BlockingError):
        get_app_config()
