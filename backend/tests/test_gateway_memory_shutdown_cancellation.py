"""Cancellation ownership regression for Gateway memory shutdown."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


@asynccontextmanager
async def _noop_langgraph_runtime(_app, _startup_config):
    yield


@pytest.mark.parametrize("config_outcome", ["ready", "blocked", "invalid"])
def test_lifespan_cancellation_drains_memory_flush_and_close(config_outcome: str, caplog: pytest.LogCaptureFixture) -> None:
    """Config errors stay best-effort; cancellation cannot detach shutdown workers."""

    async def scenario() -> None:
        from app.gateway.app import lifespan

        app = FastAPI()
        startup_config = SimpleNamespace(
            log_level="INFO",
            memory=SimpleNamespace(
                token_counting="char",
                enabled=True,
                shutdown_flush_timeout_seconds=5.0,
            ),
        )
        fake_service = MagicMock()
        fake_service.get_status.return_value = {}
        flush_started = threading.Event()
        flush_finished = threading.Event()
        allow_flush = threading.Event()
        close_started = threading.Event()
        close_finished = threading.Event()
        allow_close = threading.Event()
        config_started = threading.Event()
        allow_config = threading.Event()
        loop_thread = threading.get_ident()
        manager = MagicMock()
        manager.warm_retrieval = None
        manager.warm.return_value = True

        def blocking_flush(_timeout: float) -> bool:
            flush_started.set()
            assert allow_flush.wait(5.0)
            flush_finished.set()
            return True

        def blocking_close() -> None:
            close_started.set()
            assert flush_finished.is_set(), "memory close raced the still-running shutdown flush"
            assert allow_close.wait(5.0)
            close_finished.set()

        manager.shutdown_flush.side_effect = blocking_flush
        manager.close.side_effect = blocking_close

        async def fake_start(_startup_config, **_kwargs):
            return fake_service

        def shutdown_config():
            if config_outcome == "invalid":
                raise ValueError("invalid shutdown config")
            assert threading.get_ident() != loop_thread, "shutdown config resolution blocked the event loop"
            config_started.set()
            if config_outcome == "blocked":
                assert allow_config.wait(5.0)
            return startup_config

        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config) as get_config,
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch("app.channels.service.start_channel_service", side_effect=fake_start),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
            patch("deerflow.agents.memory.get_memory_manager", return_value=manager),
            patch("deerflow.extensions.notify.suspend_extension_system_observations"),
        ):
            context = lifespan(app)
            await context.__aenter__()
            get_config.side_effect = shutdown_config
            shutdown_task = asyncio.create_task(context.__aexit__(None, None, None))
            try:
                if config_outcome == "invalid":
                    await shutdown_task
                    assert "Failed to flush memory queue on shutdown" in caplog.text
                    assert "invalid shutdown config" in caplog.text
                    manager.shutdown_flush.assert_not_called()
                    manager.close.assert_not_called()
                    return

                assert await asyncio.to_thread(config_started.wait, 1.0)
                if config_outcome == "blocked":
                    shutdown_task.cancel("first shutdown cancellation")
                    await asyncio.sleep(0)
                    shutdown_task.cancel("cancellation during config resolution")
                    for _ in range(10):
                        await asyncio.sleep(0)
                    assert not shutdown_task.done(), "Gateway shutdown abandoned config resolution"
                    assert not flush_started.is_set()
                    assert not close_started.is_set()
                    allow_config.set()

                assert await asyncio.to_thread(flush_started.wait, 1.0)
                shutdown_task.cancel("first shutdown cancellation")
                await asyncio.sleep(0)
                shutdown_task.cancel("second shutdown cancellation")
                for _ in range(10):
                    await asyncio.sleep(0)

                assert not close_started.is_set()
                assert not shutdown_task.done(), "Gateway shutdown abandoned the in-flight memory flush"

                allow_flush.set()
                assert await asyncio.to_thread(close_started.wait, 1.0)
                assert flush_finished.is_set()
                shutdown_task.cancel("third shutdown cancellation")
                for _ in range(10):
                    await asyncio.sleep(0)
                assert not shutdown_task.done(), "Gateway shutdown abandoned the in-flight memory close"

                allow_close.set()
                with pytest.raises(asyncio.CancelledError) as exc_info:
                    await shutdown_task
                assert exc_info.value.args == ("first shutdown cancellation",)
                assert close_finished.is_set()
            finally:
                allow_config.set()
                allow_flush.set()
                allow_close.set()
                await asyncio.gather(shutdown_task, return_exceptions=True)

    asyncio.run(scenario())
