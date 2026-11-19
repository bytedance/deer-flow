from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.gateway import app as gateway_app
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
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


@pytest.mark.asyncio
async def test_gateway_shutdown_timeout_does_not_cancel_batch_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    poller_entered = asyncio.Event()
    poller_cancelled = asyncio.Event()
    release_poller = asyncio.Event()

    async def reluctant_poller() -> None:
        poller_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            poller_cancelled.set()
            await release_poller.wait()

    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )
    monkeypatch.setattr(service, "_run", reluctant_poller)
    await service.start()
    original_poller = service._poller
    await asyncio.wait_for(poller_entered.wait(), timeout=1)

    app = FastAPI()
    app.state.subagent_batch_service = service
    app.state.subagent_batches_available = True
    monkeypatch.setattr(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.01)

    with caplog.at_level(logging.WARNING, logger="app.gateway.app"):
        await gateway_app._shutdown_subagent_batch_service(app)
    await asyncio.wait_for(poller_cancelled.wait(), timeout=1)

    cleanup_task = service._stop_cleanup_task
    assert cleanup_task is not None
    assert not cleanup_task.done()
    assert original_poller is not None
    assert not original_poller.done()
    assert not original_poller.cancelled()
    assert service._stopping
    with pytest.raises(RuntimeError, match="before stop completes"):
        await service.start()

    retry_stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert service._stop_cleanup_task is cleanup_task
    release_poller.set()
    await asyncio.wait_for(retry_stop, timeout=1)

    assert service._poller is None
    assert service._stop_cleanup_task is cleanup_task
    assert cleanup_task.done()
    assert not service._stopping
    assert "Subagent batch service shutdown exceeded" in caplog.text

    await service.start()
    restarted_poller = service._poller
    assert restarted_poller is not None
    assert restarted_poller is not original_poller
    await asyncio.wait_for(service.stop(), timeout=1)
    assert restarted_poller.done()
    assert service._poller is None


@pytest.mark.asyncio
async def test_lifespan_bounds_hung_subagent_batch_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def hang() -> None:
        await asyncio.sleep(3600)

    service = MagicMock()
    service.stop = AsyncMock(side_effect=hang)

    @asynccontextmanager
    async def _runtime_with_hung_batch_service(app: FastAPI, _startup_config: object):
        app.state.subagent_batch_service = service
        app.state.subagent_batches_available = True
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
        patch("app.gateway.app.langgraph_runtime", _runtime_with_hung_batch_service),
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
    assert app.state.subagent_batches_available is False
    service.stop.assert_awaited_once()
    assert "Subagent batch service shutdown exceeded" in caplog.text


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
