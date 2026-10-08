from __future__ import annotations

import asyncio
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.gateway import app as gateway_app
from deerflow.subagents import batch_service as batch_service_module
from deerflow.subagents.batch_service import SubagentBatchService


@pytest.mark.asyncio
async def test_subagent_batch_service_shutdown_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def hang() -> None:
        await asyncio.sleep(3600)

    app = FastAPI()
    service = MagicMock()
    service.stop = AsyncMock(side_effect=hang)
    app.state.subagent_batch_service = service
    app.state.subagent_batches_available = True
    monkeypatch.setattr(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.01)

    started = asyncio.get_running_loop().time()
    with caplog.at_level(logging.WARNING, logger="app.gateway.app"):
        await gateway_app._shutdown_subagent_batch_service(app)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.5
    assert app.state.subagent_batches_available is False
    service.stop.assert_awaited_once()
    assert "Subagent batch service shutdown exceeded" in caplog.text


def test_lifespan_uses_bounded_subagent_batch_shutdown() -> None:
    source = inspect.getsource(gateway_app.lifespan)
    assert "await _shutdown_subagent_batch_service(app)" in source


@pytest.mark.asyncio
async def test_batch_stop_requests_owned_cancellation_before_poller_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_poller = asyncio.Event()
    poller_cancelled = asyncio.Event()
    requested: list[str] = []

    async def slow_poller() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            poller_cancelled.set()
            await release_poller.wait()

    async def item_work() -> None:
        await asyncio.sleep(3600)

    service = SubagentBatchService.__new__(SubagentBatchService)
    service._stop = asyncio.Event()
    service._poller = asyncio.create_task(slow_poller())
    item_task = asyncio.create_task(item_work())
    service._executions = {"item-1": item_task}
    service._execution_ids = {"item-1": "execution-1"}
    service._item_batches = {"item-1": "batch-1"}

    monkeypatch.setattr(
        batch_service_module,
        "request_cancel_background_task",
        requested.append,
    )

    stop_task = asyncio.create_task(service.stop())
    await poller_cancelled.wait()

    assert requested == ["execution-1"]
    assert item_task.cancelled() or item_task.cancelling()

    release_poller.set()
    await stop_task
