from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.gateway import app as gateway_app


@pytest.mark.asyncio
async def test_scheduled_task_service_shutdown_is_bounded(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    async def hang() -> None:
        await asyncio.sleep(3600)

    app = FastAPI()
    service = MagicMock()
    service.stop = AsyncMock(side_effect=hang)
    app.state.scheduled_task_service = service
    monkeypatch.setattr(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.01)

    started = asyncio.get_running_loop().time()
    with caplog.at_level(logging.WARNING, logger="app.gateway.app"):
        await gateway_app._shutdown_scheduled_task_service(app)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.5
    service.stop.assert_awaited_once()
    assert "Scheduled task service shutdown exceeded" in caplog.text


@pytest.mark.asyncio
async def test_lifespan_bounds_hung_scheduled_task_shutdown(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    async def hang() -> None:
        await asyncio.sleep(3600)

    service = MagicMock()
    service.stop = AsyncMock(side_effect=hang)

    @asynccontextmanager
    async def _runtime_with_hung_scheduler(app: FastAPI, _startup_config: object):
        app.state.scheduled_task_service = service
        yield

    app = FastAPI()
    startup_config = MagicMock()
    startup_config.log_level = "INFO"
    startup_config.memory.enabled = False
    startup_config.memory.shutdown_flush_timeout_seconds = 5.0
    startup_config.scheduler.enabled = False
    monkeypatch.setattr(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.01)

    channel_service = MagicMock()
    channel_service.get_status.return_value = {}
    patches = [
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _runtime_with_hung_scheduler),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", AsyncMock(return_value=channel_service)),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
        patch("deerflow.mcp.session_pool.get_session_pool", return_value=MagicMock(close_all=AsyncMock())),
        patch(
            "deerflow.community.browser_automation.get_browser_session_manager",
            return_value=MagicMock(close_all_sessions=AsyncMock(return_value=0)),
        ),
    ]

    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        with caplog.at_level(logging.WARNING, logger="app.gateway.app"):
            async with gateway_app.lifespan(app):
                started = asyncio.get_running_loop().time()
            elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.5
    service.stop.assert_awaited_once()
    assert "Scheduled task service shutdown exceeded" in caplog.text
