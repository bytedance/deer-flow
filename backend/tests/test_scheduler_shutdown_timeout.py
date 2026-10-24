from __future__ import annotations

import asyncio
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock

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


def test_lifespan_uses_bounded_scheduled_task_shutdown() -> None:
    source = inspect.getsource(gateway_app.lifespan)
    assert "await _shutdown_scheduled_task_service(app)" in source
