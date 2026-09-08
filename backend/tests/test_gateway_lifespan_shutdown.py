"""Regression tests for Gateway lifespan shutdown.

These tests guard the invariant that lifespan shutdown is *bounded*: a
misbehaving channel whose ``stop()`` blocks forever must not keep the
uvicorn worker alive. A hung worker is the precondition for the
signal-reentrancy deadlock described in
``app.gateway.app._SHUTDOWN_HOOK_TIMEOUT_SECONDS``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


@asynccontextmanager
async def _noop_langgraph_runtime(_app, _startup_config):
    yield


async def _run_lifespan_with_hanging_stop() -> float:
    """Drive the lifespan context with stop_channel_service hanging forever.

    Returns the elapsed wall-clock seconds.
    """
    from app.gateway.app import _SHUTDOWN_HOOK_TIMEOUT_SECONDS, lifespan

    async def hang_forever() -> None:
        await asyncio.sleep(3600)

    app = FastAPI()
    startup_config = MagicMock()
    startup_config.log_level = "INFO"
    # Keep this test focused on the channel-hang timing: skip the memory drain.
    startup_config.memory.enabled = False
    startup_config.memory.shutdown_flush_timeout_seconds = 5.0
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    close_oidc_service = AsyncMock()

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("app.gateway.app.auth.close_oidc_service", close_oidc_service),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", side_effect=hang_forever),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
    ):
        loop = asyncio.get_event_loop()
        start = loop.time()
        async with lifespan(app):
            pass
        elapsed = loop.time() - start

    close_oidc_service.assert_awaited_once()
    assert _SHUTDOWN_HOOK_TIMEOUT_SECONDS < 30.0, "Timeout constant must stay modest"
    return elapsed


def test_shutdown_is_bounded_when_channel_stop_hangs():
    """Lifespan exit must complete near the configured timeout, not hang."""
    from app.gateway.app import _SHUTDOWN_HOOK_TIMEOUT_SECONDS

    elapsed = asyncio.run(_run_lifespan_with_hanging_stop())

    # Generous upper bound: timeout + 2s slack for scheduling overhead.
    assert elapsed < _SHUTDOWN_HOOK_TIMEOUT_SECONDS + 2.0, f"Lifespan shutdown took {elapsed:.2f}s; expected <= {_SHUTDOWN_HOOK_TIMEOUT_SECONDS + 2.0:.1f}s"
    # Lower bound: the wait_for should actually have waited.
    assert elapsed >= _SHUTDOWN_HOOK_TIMEOUT_SECONDS - 0.5, f"Lifespan exited too quickly ({elapsed:.2f}s); wait_for may not have been invoked."


def test_shutdown_is_bounded_when_subagent_batch_stop_hangs():
    import app.gateway.app as gateway_app

    class HangingBatchStop:
        def __await__(self):
            return asyncio.Event().wait().__await__()

    async def run() -> tuple[float, MagicMock, list[float]]:
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status = MagicMock(return_value={})
        stop_batch = MagicMock(return_value=HangingBatchStop())
        batch_wait_for_timeouts: list[float] = []
        original_wait_for = asyncio.wait_for

        async def recording_wait_for(awaitable, timeout):
            if isinstance(awaitable, HangingBatchStop):
                batch_wait_for_timeouts.append(timeout)
            return await original_wait_for(awaitable, timeout)

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        with (
            patch.object(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.05),
            patch.object(gateway_app.asyncio, "wait_for", side_effect=recording_wait_for),
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch("app.channels.service.start_channel_service", side_effect=fake_start),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
        ):
            start = asyncio.get_running_loop().time()
            async with gateway_app.lifespan(app):
                app.state.subagent_batch_service = SimpleNamespace(stop=stop_batch)
            elapsed = asyncio.get_running_loop().time() - start
        return elapsed, stop_batch, batch_wait_for_timeouts

    elapsed, stop_batch, batch_wait_for_timeouts = asyncio.run(asyncio.wait_for(run(), timeout=2.0))

    stop_batch.assert_called_once_with()
    assert elapsed >= 0.04
    assert batch_wait_for_timeouts == [0.05]


def test_real_task_cancellation_does_not_leave_hanging_scheduled_stop_unbounded():
    import app.gateway.app as gateway_app

    async def run() -> tuple[float, AsyncMock]:
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status.return_value = {}
        oidc_close_started = asyncio.Event()

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        async def cancellable_oidc_close() -> None:
            oidc_close_started.set()
            await asyncio.Event().wait()

        async def hang_forever() -> None:
            await asyncio.Event().wait()

        stop_scheduled = AsyncMock(side_effect=hang_forever)
        with (
            patch.object(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.05),
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", side_effect=cancellable_oidc_close),
            patch("app.channels.service.start_channel_service", side_effect=fake_start),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
        ):
            context = gateway_app.lifespan(app)
            await context.__aenter__()
            app.state.scheduled_task_service = SimpleNamespace(stop=stop_scheduled)
            started = asyncio.get_running_loop().time()
            shutdown = asyncio.create_task(context.__aexit__(None, None, None))
            await asyncio.wait_for(oidc_close_started.wait(), timeout=1.0)
            shutdown.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(shutdown, timeout=1.0)
            elapsed = asyncio.get_running_loop().time() - started
        return elapsed, stop_scheduled

    elapsed, stop_scheduled = asyncio.run(run())

    stop_scheduled.assert_awaited_once_with()
    assert 0.04 <= elapsed < 1.0


def test_shutdown_is_bounded_when_mcp_task_stop_hangs():
    import app.gateway.app as gateway_app

    async def run() -> tuple[float, AsyncMock]:
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status.return_value = {}

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        async def hang_forever() -> None:
            await asyncio.Event().wait()

        stop_mcp = AsyncMock(side_effect=hang_forever)
        with (
            patch.object(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.05),
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch("app.channels.service.start_channel_service", side_effect=fake_start),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
        ):
            started = asyncio.get_running_loop().time()
            async with gateway_app.lifespan(app):
                app.state.mcp_task_service = SimpleNamespace(stop=stop_mcp)
            elapsed = asyncio.get_running_loop().time() - started
        return elapsed, stop_mcp

    elapsed, stop_mcp = asyncio.run(asyncio.wait_for(run(), timeout=1.0))

    stop_mcp.assert_awaited_once_with()
    assert 0.04 <= elapsed < 1.0


def test_subagent_batch_fatal_does_not_skip_remaining_gateway_cleanup():
    import app.gateway.app as gateway_app

    class BatchStopFatal(BaseException):
        pass

    class BrowserCloseFatal(BaseException):
        pass

    async def run() -> tuple[BatchStopFatal, AsyncMock, MagicMock]:
        fatal = BatchStopFatal("batch worker fatal")
        later_fatal = BrowserCloseFatal("browser close fatal")
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = True
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status.return_value = {}
        browser_manager = SimpleNamespace(
            close_all_sessions=AsyncMock(side_effect=later_fatal),
        )
        memory_manager = MagicMock()
        memory_manager.warm.return_value = None
        memory_manager.shutdown_flush.return_value = True

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch(
                "app.gateway.app.get_gateway_config",
                return_value=MagicMock(host="x", port=0),
            ),
            patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch(
                "app.channels.service.start_channel_service",
                side_effect=fake_start,
            ),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
            patch(
                "deerflow.community.browser_automation.get_browser_session_manager",
                return_value=browser_manager,
            ),
            patch(
                "deerflow.agents.memory.get_memory_manager",
                return_value=memory_manager,
            ),
        ):
            with pytest.raises(BatchStopFatal) as raised:
                async with gateway_app.lifespan(app):
                    app.state.subagent_batch_service = SimpleNamespace(
                        stop=AsyncMock(side_effect=fatal),
                    )

        assert raised.value is fatal
        return fatal, browser_manager.close_all_sessions, memory_manager

    _fatal, close_browser_sessions, memory_manager = asyncio.run(run())

    close_browser_sessions.assert_awaited_once()
    memory_manager.shutdown_flush.assert_called_once_with(5.0)
    memory_manager.close.assert_called_once_with()


def test_shutdown_fatal_beats_cancellation_and_runtime_exit_error():
    import app.gateway.app as gateway_app

    class BatchStopFatal(BaseException):
        pass

    class RuntimeExitFatal(BaseException):
        pass

    async def run() -> None:
        cancellation = asyncio.CancelledError("early cancellation")
        batch_fatal = BatchStopFatal("batch fatal")
        runtime_fatal = RuntimeExitFatal("runtime exit fatal")
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status.return_value = {}

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        @asynccontextmanager
        async def failing_runtime(_app, _startup_config):
            try:
                yield
            finally:
                raise runtime_fatal

        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", failing_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock(side_effect=cancellation)),
            patch("app.channels.service.start_channel_service", side_effect=fake_start),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
            patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
        ):
            with pytest.raises(BatchStopFatal) as raised:
                async with gateway_app.lifespan(app):
                    app.state.subagent_batch_service = SimpleNamespace(
                        stop=AsyncMock(side_effect=batch_fatal),
                    )

        assert raised.value is batch_fatal

    asyncio.run(run())


def test_langgraph_runtime_startup_error_is_not_masked():
    import app.gateway.app as gateway_app

    startup_error = RuntimeError("runtime startup failed")

    @asynccontextmanager
    async def failing_runtime(_app, _startup_config):
        raise startup_error
        yield

    async def run() -> None:
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", failing_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
        ):
            with pytest.raises(RuntimeError) as raised:
                async with gateway_app.lifespan(FastAPI()):
                    pass

        assert raised.value is startup_error

    asyncio.run(run())


def test_host_cancellation_during_oidc_close_runs_remaining_gateway_cleanup():
    import app.gateway.app as gateway_app

    async def run() -> tuple[asyncio.CancelledError, AsyncMock, MagicMock]:
        cancellation = asyncio.CancelledError("host shutdown cancelled")
        later_cancellation = asyncio.CancelledError("later shutdown cancellation")
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = True
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status.return_value = {}
        stop_channel_service = AsyncMock()
        browser_manager = SimpleNamespace(
            close_all_sessions=AsyncMock(return_value=1),
        )
        memory_manager = MagicMock()
        memory_manager.warm.return_value = None
        memory_manager.shutdown_flush.return_value = True

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        @asynccontextmanager
        async def failing_runtime(_app, _startup_config):
            try:
                yield
            finally:
                raise RuntimeError("ordinary runtime exit error")

        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch(
                "app.gateway.app.get_gateway_config",
                return_value=MagicMock(host="x", port=0),
            ),
            patch("app.gateway.app.langgraph_runtime", failing_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch(
                "app.gateway.app.auth.close_oidc_service",
                AsyncMock(side_effect=cancellation),
            ),
            patch(
                "app.channels.service.start_channel_service",
                side_effect=fake_start,
            ),
            patch(
                "app.channels.service.stop_channel_service",
                stop_channel_service,
            ),
            patch(
                "deerflow.community.browser_automation.get_browser_session_manager",
                return_value=browser_manager,
            ),
            patch(
                "deerflow.agents.memory.get_memory_manager",
                return_value=memory_manager,
            ),
        ):
            with pytest.raises(asyncio.CancelledError) as raised:
                async with gateway_app.lifespan(app):
                    app.state.subagent_batch_service = SimpleNamespace(
                        stop=AsyncMock(side_effect=later_cancellation),
                    )

        assert raised.value is cancellation
        return cancellation, browser_manager.close_all_sessions, memory_manager

    _cancellation, close_browser_sessions, memory_manager = asyncio.run(run())

    close_browser_sessions.assert_awaited_once()
    memory_manager.shutdown_flush.assert_called_once_with(5.0)
    memory_manager.close.assert_called_once_with()


def test_host_cancellation_during_batch_stop_runs_remaining_gateway_cleanup():
    import app.gateway.app as gateway_app

    async def run() -> tuple[asyncio.CancelledError, AsyncMock, MagicMock]:
        cancellation = asyncio.CancelledError("host shutdown cancelled")
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = True
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status.return_value = {}
        browser_manager = SimpleNamespace(
            close_all_sessions=AsyncMock(return_value=1),
        )
        memory_manager = MagicMock()
        memory_manager.warm.return_value = None
        memory_manager.shutdown_flush.return_value = True

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch(
                "app.gateway.app.get_gateway_config",
                return_value=MagicMock(host="x", port=0),
            ),
            patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch(
                "app.channels.service.start_channel_service",
                side_effect=fake_start,
            ),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
            patch(
                "deerflow.community.browser_automation.get_browser_session_manager",
                return_value=browser_manager,
            ),
            patch(
                "deerflow.agents.memory.get_memory_manager",
                return_value=memory_manager,
            ),
        ):
            with pytest.raises(asyncio.CancelledError) as raised:
                async with gateway_app.lifespan(app):
                    app.state.subagent_batch_service = SimpleNamespace(
                        stop=AsyncMock(side_effect=cancellation),
                    )

        assert raised.value is cancellation
        return cancellation, browser_manager.close_all_sessions, memory_manager

    _cancellation, close_browser_sessions, memory_manager = asyncio.run(run())

    close_browser_sessions.assert_awaited_once()
    memory_manager.shutdown_flush.assert_called_once_with(5.0)
    memory_manager.close.assert_called_once_with()


def test_retrieval_warm_fatal_still_closes_memory_backend():
    import app.gateway.app as gateway_app

    class RetrievalWarmFatal(BaseException):
        pass

    async def run() -> tuple[RetrievalWarmFatal, MagicMock]:
        fatal = RetrievalWarmFatal("retrieval warm fatal")
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = True
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        fake_channel_service = MagicMock()
        fake_channel_service.get_status.return_value = {}
        memory_manager = MagicMock()
        memory_manager.warm.return_value = None
        memory_manager.warm_retrieval.side_effect = fatal
        memory_manager.shutdown_flush.return_value = True

        async def fake_start(_startup_config, **_kwargs):
            return fake_channel_service

        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch(
                "app.gateway.app.get_gateway_config",
                return_value=MagicMock(host="x", port=0),
            ),
            patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch(
                "app.channels.service.start_channel_service",
                side_effect=fake_start,
            ),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
            patch(
                "deerflow.community.browser_automation.get_browser_session_manager",
                return_value=SimpleNamespace(
                    close_all_sessions=AsyncMock(return_value=0),
                ),
            ),
            patch(
                "deerflow.agents.memory.get_memory_manager",
                return_value=memory_manager,
            ),
        ):
            with pytest.raises(RetrievalWarmFatal) as raised:
                async with gateway_app.lifespan(app):
                    await asyncio.sleep(0)

        assert raised.value is fatal
        return fatal, memory_manager

    _fatal, memory_manager = asyncio.run(run())

    memory_manager.shutdown_flush.assert_called_once_with(5.0)
    memory_manager.close.assert_called_once_with()


async def _run_lifespan_with_upload_staging_cleanup():
    from app.gateway.app import lifespan

    app = FastAPI()
    startup_config = SimpleNamespace(log_level="INFO", memory=SimpleNamespace(token_counting="char", enabled=False, shutdown_flush_timeout_seconds=30.0))
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})
    cleanup_upload_staging_files = MagicMock(return_value=2)
    close_oidc_service = AsyncMock()
    stop_channel_service = AsyncMock()

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("app.gateway.app.cleanup_stale_upload_staging_files", cleanup_upload_staging_files),
        patch("app.gateway.app.auth.close_oidc_service", close_oidc_service),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", stop_channel_service),
    ):
        async with lifespan(app):
            pass

    return cleanup_upload_staging_files, close_oidc_service, stop_channel_service


def test_lifespan_sweeps_upload_staging_files_on_startup():
    cleanup_upload_staging_files, close_oidc_service, stop_channel_service = asyncio.run(_run_lifespan_with_upload_staging_cleanup())

    cleanup_upload_staging_files.assert_called_once_with()
    close_oidc_service.assert_awaited_once()
    stop_channel_service.assert_awaited_once()


async def _run_lifespan_with_mcp_task_config_snapshot() -> None:
    from app.gateway.app import lifespan
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.tasks.runtime import McpTaskConfigurationError, validate_mcp_task_config_snapshot

    app = FastAPI()
    startup_config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(
            token_counting="char",
            enabled=False,
            shutdown_flush_timeout_seconds=30.0,
        ),
    )
    startup_extensions = ExtensionsConfig()
    changed_extensions = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "command": "reports-mcp",
                    "task_toolsets": [
                        {
                            "name": "reports",
                            "submit_tool": "submit_report",
                            "status_tool": "status_report",
                            "cancel_tool": "cancel_report",
                        }
                    ],
                }
            }
        }
    )
    fake_service = MagicMock()
    fake_service.get_status.return_value = {}

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=startup_extensions),
    ):
        async with lifespan(app):
            with pytest.raises(McpTaskConfigurationError, match="reports.*restart"):
                validate_mcp_task_config_snapshot(changed_extensions)

    validate_mcp_task_config_snapshot(changed_extensions)


def test_lifespan_sets_and_clears_mcp_task_config_snapshot() -> None:
    asyncio.run(_run_lifespan_with_mcp_task_config_snapshot())


async def _run_lifespan_with_memory_flush(
    *,
    enabled: bool,
    flush_return: bool | Exception,
    shutdown_events: list[str] | None = None,
) -> MagicMock:
    """Drive lifespan with a spied memory manager.shutdown_flush.

    Returns the manager mock so the caller can assert the shutdown flush was
    reached (and with what timeout). The host calls ``shutdown_flush``
    unconditionally when memory is enabled -- there is no host-level
    ``pending_count/is_processing`` gate, because the backend short-circuits on
    an idle buffer and keeping the in-flight race inside the backend means the
    host cannot "forget" it (review #6 on the original PR).
    """
    from app.gateway.app import lifespan

    app = FastAPI()
    startup_config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(
            token_counting="char",
            enabled=enabled,
            shutdown_flush_timeout_seconds=5.0,
        ),
    )
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})
    close_oidc_service = AsyncMock()
    stop_channel_service = AsyncMock()

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    manager = MagicMock()
    if isinstance(flush_return, Exception):
        manager.shutdown_flush.side_effect = flush_return
    elif shutdown_events is not None:

        def record_memory_flush(_timeout: float) -> bool:
            shutdown_events.append("memory_flush_started")
            return flush_return

        manager.shutdown_flush.side_effect = record_memory_flush
    else:
        manager.shutdown_flush.return_value = flush_return

    suspend_system_observations = MagicMock()
    if shutdown_events is not None:
        suspend_system_observations.side_effect = lambda: shutdown_events.append("system_observations_suspended")

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("app.gateway.app.auth.close_oidc_service", close_oidc_service),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", stop_channel_service),
        patch("deerflow.agents.memory.get_memory_manager", return_value=manager),
        patch("deerflow.extensions.notify.suspend_extension_system_observations", suspend_system_observations),
    ):
        async with lifespan(app):
            pass

    return manager


def test_lifespan_drains_memory_on_shutdown_with_configured_timeout(caplog) -> None:
    """When memory is enabled, shutdown calls manager.shutdown_flush with the
    configured timeout (asserts the timeout is forwarded, review #3) and logs
    'completed' at INFO when the drain finishes."""
    caplog.set_level(logging.INFO, logger="app.gateway.app")
    manager = asyncio.run(_run_lifespan_with_memory_flush(enabled=True, flush_return=True))
    manager.shutdown_flush.assert_called_once_with(5.0)
    assert any(r.levelno == logging.INFO and "flush completed" in r.message for r in caplog.records)


def test_lifespan_suspends_system_observations_before_memory_flush() -> None:
    """Shutdown-flushed memory calls cannot enqueue observations onto a dying loop."""
    shutdown_events: list[str] = []

    asyncio.run(
        _run_lifespan_with_memory_flush(
            enabled=True,
            flush_return=True,
            shutdown_events=shutdown_events,
        )
    )

    assert shutdown_events == ["system_observations_suspended", "memory_flush_started"]


def test_lifespan_warns_when_memory_flush_does_not_finish(caplog) -> None:
    """A False return (timeout/failure) is the path operators actually see when
    K8s SIGKILLs the drain; the host must log a WARNING (not 'completed'), so
    the loss risk is visible (review #3 False-branch coverage; review #2/#4
    failed-flush semantics)."""
    caplog.set_level(logging.WARNING, logger="app.gateway.app")
    manager = asyncio.run(_run_lifespan_with_memory_flush(enabled=True, flush_return=False))
    manager.shutdown_flush.assert_called_once_with(5.0)
    assert any(r.levelno == logging.WARNING and "did not finish" in r.message for r in caplog.records)
    assert not any("flush completed" in r.message for r in caplog.records)


def test_lifespan_skips_memory_flush_when_disabled() -> None:
    """memory.enabled=False skips the drain entirely."""
    manager = asyncio.run(_run_lifespan_with_memory_flush(enabled=False, flush_return=True))
    manager.shutdown_flush.assert_not_called()


def test_lifespan_closes_memory_manager_when_flush_raises() -> None:
    """Derived retrieval resources are released even when queue drain fails."""
    manager = asyncio.run(_run_lifespan_with_memory_flush(enabled=True, flush_return=RuntimeError("flush failed")))
    manager.shutdown_flush.assert_called_once_with(5.0)
    manager.close.assert_called_once_with()


# ── startup warm-up log accuracy ────────────────────────────────────────────


async def _run_lifespan_with_warm_return(warm_return: bool | None) -> MagicMock:
    """Drive lifespan with a spied ``manager.warm`` returning ``warm_return``.

    The startup warm block reads the tri-state return: None = nothing to warm
    (logs "skipping"), True = warmed, False = failed (logs WARNING). Returns the
    manager mock so the caller can assert warm was reached.
    """
    from app.gateway.app import lifespan

    app = FastAPI()
    startup_config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(
            token_counting="char",
            enabled=False,
            shutdown_flush_timeout_seconds=5.0,
        ),
    )
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})
    close_oidc_service = AsyncMock()
    stop_channel_service = AsyncMock()

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    manager = MagicMock()
    manager.warm.return_value = warm_return

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.auth.close_oidc_service", close_oidc_service),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", stop_channel_service),
        patch("deerflow.agents.memory.get_memory_manager", return_value=manager),
    ):
        async with lifespan(app):
            pass

    return manager


def test_lifespan_logs_skipping_when_backend_has_nothing_to_warm(caplog) -> None:
    """A backend whose warm() returns None (base default -- nothing to warm,
    e.g. noop) logs "skipping" at INFO, not the misleading "warmed successfully"
    (a non-DeerMem backend never touched the tiktoken cache)."""
    caplog.set_level(logging.INFO, logger="app.gateway.app")
    manager = asyncio.run(_run_lifespan_with_warm_return(None))
    manager.warm.assert_called_once_with()
    assert any(r.levelno == logging.INFO and "nothing to warm" in r.message for r in caplog.records)
    assert not any("warmed successfully" in r.message for r in caplog.records)


def test_lifespan_warns_when_warm_returns_false(caplog) -> None:
    """warm()=False means warming was attempted and failed; the host logs a
    WARNING so the operator sees the character-based-fallback degradation."""
    caplog.set_level(logging.WARNING, logger="app.gateway.app")
    manager = asyncio.run(_run_lifespan_with_warm_return(False))
    manager.warm.assert_called_once_with()
    assert any(r.levelno == logging.WARNING and "warm-up failed" in r.message for r in caplog.records)


async def _run_lifespan_with_slow_retrieval_warm() -> float:
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
    release_rebuild = threading.Event()
    manager = MagicMock()
    manager.warm_retrieval.side_effect = lambda: release_rebuild.wait(5.0) or True
    manager.warm.return_value = True
    manager.shutdown_flush.return_value = True

    async def fake_start(_startup_config):
        return fake_service

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.agents.memory.get_memory_manager", return_value=manager),
    ):
        context = lifespan(app)
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        try:
            await asyncio.wait_for(context.__aenter__(), timeout=1.0)
            startup_elapsed = loop.time() - started_at
        finally:
            release_rebuild.set()
        await context.__aexit__(None, None, None)
    return startup_elapsed


def test_lifespan_does_not_wait_for_retrieval_rebuild_before_serving() -> None:
    assert asyncio.run(_run_lifespan_with_slow_retrieval_warm()) < 1.0


async def _run_shutdown_with_blocked_retrieval_warm() -> tuple[float, MagicMock]:
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
    rebuild_started = threading.Event()
    release_rebuild = threading.Event()
    manager = MagicMock()

    def block_rebuild() -> bool:
        rebuild_started.set()
        release_rebuild.wait(5.0)
        return True

    manager.warm_retrieval.side_effect = block_rebuild
    manager.warm.return_value = True
    manager.shutdown_flush.return_value = True

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app._RETRIEVAL_WARM_SHUTDOWN_TIMEOUT_SECONDS", 0.01),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.agents.memory.get_memory_manager", return_value=manager),
    ):
        context = lifespan(app)
        await context.__aenter__()
        assert await asyncio.to_thread(rebuild_started.wait, 1.0)
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        try:
            await context.__aexit__(None, None, None)
        finally:
            release_rebuild.set()
        shutdown_elapsed = loop.time() - started_at

    return shutdown_elapsed, manager


def test_lifespan_preserves_flush_budget_when_retrieval_warm_is_still_running() -> None:
    shutdown_elapsed, manager = asyncio.run(_run_shutdown_with_blocked_retrieval_warm())

    assert shutdown_elapsed < 1.0
    manager.shutdown_flush.assert_called_once_with(5.0)
    manager.close.assert_not_called()
