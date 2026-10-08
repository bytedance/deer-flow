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
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


@asynccontextmanager
async def _noop_langgraph_runtime(_app, _startup_config):
    yield


@asynccontextmanager
async def _langgraph_runtime_with_scheduler_repositories(app, _startup_config):
    app.state.scheduled_task_repo = object()
    app.state.scheduled_task_run_repo = object()
    yield


def test_enabled_scheduler_start_failure_aborts_gateway_lifespan():
    """An enabled scheduler must fail lifespan before channel or request admission."""
    from app.gateway.app import lifespan

    async def scenario():
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        startup_config.scheduler.enabled = True
        startup_config.scheduler.multi_instance = False
        startup_config.scheduler.poll_interval_seconds = 5
        startup_config.scheduler.lease_seconds = 120
        startup_config.scheduler.max_concurrent_runs = 3
        # Set explicitly: a bare MagicMock attribute must never reach the
        # per-owner cap the drain query compares against.
        startup_config.scheduler.max_concurrent_runs_per_user = 2
        startup_config.scheduler.queue_timeout_seconds = 3600
        startup_config.run_ownership.grace_seconds = 10
        channel_service = MagicMock()
        channel_service.get_status.return_value = {}
        start_channel_service = AsyncMock(return_value=channel_service)
        scheduler_service = MagicMock()
        scheduler_service.start = AsyncMock(side_effect=RuntimeError("scheduled recovery failed"))
        scheduler_service.stop = AsyncMock()

        with (
            patch("app.gateway.app.get_app_config", return_value=startup_config),
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", _langgraph_runtime_with_scheduler_repositories),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch("app.channels.service.start_channel_service", start_channel_service),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
            patch("app.scheduler.ScheduledTaskService", return_value=scheduler_service) as service_class,
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
        ):
            with pytest.raises(RuntimeError, match="scheduled recovery failed"):
                async with lifespan(app):
                    pass

        scheduler_service.start.assert_awaited_once()
        start_channel_service.assert_not_awaited()
        # The startup-captured per-owner cap reaches the service unchanged.
        assert service_class.call_args.kwargs["max_concurrent_runs_per_user"] == 2
        assert service_class.call_args.kwargs["max_concurrent_runs"] == 3

    asyncio.run(scenario())


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


def test_personal_mcp_authority_spans_runtime_startup_and_shutdown():
    from deerflow.mcp import personal_access

    events = []
    previous = personal_access._admin_checker

    @asynccontextmanager
    async def checked_runtime(_app, _config):
        checker = personal_access._admin_checker
        assert checker is not None and checker is not previous
        events.append("start")
        try:
            yield
        finally:
            assert personal_access._admin_checker is checker
            events.append("stop")

    with patch(f"{__name__}._noop_langgraph_runtime", checked_runtime):
        asyncio.run(_run_lifespan_with_upload_staging_cleanup())

    assert events == ["start", "stop"]
    assert personal_access._admin_checker is previous


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


@pytest.mark.asyncio
async def test_lifespan_pins_batch_service_to_app_extensions(monkeypatch):
    import deerflow.extensions as extensions
    from app.gateway.app import lifespan
    from deerflow.config.subagent_batches_config import SubagentBatchesConfig
    from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
    from deerflow.extensions.registry import ExtensionRegistry

    app = FastAPI()
    snapshot = ExtensionRegistry().build()
    app.state.extensions = snapshot
    monkeypatch.setattr(extensions, "_loaded", ExtensionRegistry().build())
    startup_config = MagicMock()
    startup_config.log_level = "INFO"
    startup_config.memory.enabled = False
    startup_config.scheduler.enabled = False
    startup_config.mcp_tasks.enabled = False
    startup_config.subagent_batches = SubagentBatchesConfig(enabled=True)
    startup_config.subagent_runtime = SubagentRuntimeConfig()
    channel_service = MagicMock()
    channel_service.get_status.return_value = {}

    @asynccontextmanager
    async def runtime(app, _config):
        app.state.subagent_batch_repo = object()
        yield

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", runtime),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", AsyncMock(return_value=channel_service)),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
        patch("deerflow.subagents.batch_service.SubagentBatchService.start", AsyncMock()),
        patch("deerflow.subagents.batch_service.SubagentBatchService.stop", AsyncMock()),
    ):
        async with lifespan(app):
            assert app.state.subagent_batch_service._extensions is snapshot


def _gateway_lifespan_patches(startup_config, *, pool=None, browser_manager=None):
    """Common patch set for driving the Gateway lifespan in a unit test."""
    channel_service = MagicMock()
    channel_service.get_status.return_value = {}
    patches = [
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", AsyncMock(return_value=channel_service)),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
    ]
    if pool is not None:
        patches.append(patch("deerflow.mcp.session_pool.get_session_pool", return_value=pool))
    if browser_manager is not None:
        patches.append(
            patch(
                "deerflow.community.browser_automation.get_browser_session_manager",
                return_value=browser_manager,
            )
        )
    return patches


def test_lifespan_closes_pooled_mcp_sessions_on_shutdown():
    """Pooled MCP sessions must be closed while the worker is still shutting down.

    Each pooled session owns a live transport (a stdio subprocess, or an
    SSE/HTTP connection) held by a dedicated owner task. Nothing else can reach
    that task once the event loop stops, so lifespan shutdown is the only place
    its ``__aexit__`` can run. The browser session manager is closed here for
    the same reason; the MCP pool used to be skipped.
    """
    from app.gateway.app import lifespan

    async def scenario():
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        pool = MagicMock()
        pool.close_all = AsyncMock()

        with ExitStack() as stack:
            for patcher in _gateway_lifespan_patches(startup_config, pool=pool):
                stack.enter_context(patcher)
            async with lifespan(app):
                pass

        pool.close_all.assert_awaited_once()

    asyncio.run(scenario())


def test_lifespan_continues_when_mcp_close_fails():
    """A failing MCP close must not abort the remaining shutdown hooks.

    Shutdown is best-effort by design: every hook is isolated so one broken
    teardown cannot strand the others.
    """
    from app.gateway.app import lifespan

    async def scenario():
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        pool = MagicMock()
        pool.close_all = AsyncMock(side_effect=RuntimeError("close failed"))
        browser_manager = MagicMock()
        browser_manager.close_all_sessions = AsyncMock(return_value=0)

        with ExitStack() as stack:
            for patcher in _gateway_lifespan_patches(startup_config, pool=pool, browser_manager=browser_manager):
                stack.enter_context(patcher)
            async with lifespan(app):
                pass

        pool.close_all.assert_awaited_once()
        browser_manager.close_all_sessions.assert_awaited_once()

    asyncio.run(scenario())


def test_lifespan_closes_mcp_sessions_created_during_run_drain():
    """An active run can acquire a session after other shutdown hooks begin."""
    from app.gateway.app import lifespan
    from deerflow.mcp.session_pool import MCPSessionPool
    from deerflow.runtime import RunManager, RunStatus

    async def scenario():
        app = FastAPI()
        startup_config = MagicMock()
        startup_config.log_level = "INFO"
        startup_config.memory.enabled = False
        startup_config.memory.shutdown_flush_timeout_seconds = 5.0
        pool = MCPSessionPool()
        run_manager = RunManager()
        record = await run_manager.create("mcp-shutdown-race")
        await run_manager.set_status(record.run_id, RunStatus.running)
        resume = asyncio.Event()
        session_created = asyncio.Event()
        transport_closed = asyncio.Event()

        class SessionContext:
            async def __aenter__(self):
                self.owner = asyncio.current_task()
                return SimpleNamespace(initialize=AsyncMock())

            async def __aexit__(self, *_args):
                assert asyncio.current_task() is self.owner
                transport_closed.set()

        async def active_run():
            await resume.wait()
            await pool.get_session("server", "thread", {"transport": "stdio", "command": "unused"})
            session_created.set()
            await asyncio.Event().wait()

        @asynccontextmanager
        async def runtime(_app, _config):
            record.task = asyncio.create_task(active_run())
            try:
                yield
            finally:
                await run_manager.shutdown(timeout=1.0)

        async def shutdown_memory_backend(**_kwargs):
            # This hook runs before langgraph_runtime drains the active run.
            resume.set()
            await asyncio.wait_for(session_created.wait(), timeout=5)

        try:
            with ExitStack() as stack:
                for patcher in _gateway_lifespan_patches(startup_config, pool=pool):
                    stack.enter_context(patcher)
                stack.enter_context(patch("app.gateway.app.langgraph_runtime", runtime))
                stack.enter_context(patch("app.gateway.app._shutdown_memory_backend", shutdown_memory_backend))
                stack.enter_context(patch("langchain_mcp_adapters.sessions.create_session", side_effect=lambda _connection: SessionContext()))
                async with lifespan(app):
                    pass

            assert record.task is not None and record.task.done()
            assert transport_closed.is_set()
            assert not pool._entries
        finally:
            resume.set()
            if record.task is not None and not record.task.done():
                record.task.cancel()
                await asyncio.gather(record.task, return_exceptions=True)
            await pool.close_all()

    asyncio.run(scenario())


# ── notification delivery worker wiring (issue #4254) ───────────────────────


@asynccontextmanager
async def _langgraph_with_scheduled_repos(app, _startup_config):
    app.state.scheduled_task_repo = MagicMock()
    app.state.scheduled_task_run_repo = MagicMock()
    yield


def _notification_startup_config(*, channel_connections_enabled: bool = True):
    from deerflow.config.channel_connections_config import ChannelConnectionsConfig

    return SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(token_counting="char", enabled=False, shutdown_flush_timeout_seconds=5.0),
        scheduler=SimpleNamespace(
            enabled=False,
            poll_interval_seconds=5,
            lease_seconds=30,
            max_concurrent_runs=1,
            max_concurrent_runs_per_user=2,
            multi_instance=False,
            queue_timeout_seconds=3600,
        ),
        run_ownership=SimpleNamespace(grace_seconds=30),
        channel_connections=ChannelConnectionsConfig.model_validate({"enabled": channel_connections_enabled}),
    )


async def _run_lifespan_with_notification_worker(*, channel_service_available: bool, visible_only_after_start: bool = False):
    from app.gateway.app import lifespan

    app = FastAPI()
    startup_config = _notification_startup_config()
    close_oidc_service = AsyncMock()
    stop_channel_service = AsyncMock()
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})
    worker_start = AsyncMock()
    worker_stop = AsyncMock()
    worker_instance = MagicMock()
    worker_instance.start = worker_start
    worker_instance.stop = worker_stop
    scheduled_service = MagicMock()
    scheduled_service.start = AsyncMock()
    scheduled_service.stop = AsyncMock()
    session_factory = MagicMock()
    shutdown_events: list[str] = []

    channel_service_started = False

    async def fake_start(_startup_config, **_kwargs):
        nonlocal channel_service_started
        channel_service_started = True
        return fake_service

    def fake_get_channel_service():
        # The real accessor returns None until start_channel_service() has run.
        if not channel_service_available or (visible_only_after_start and not channel_service_started):
            return None
        return fake_service

    async def record_worker_stop():
        shutdown_events.append("worker")

    async def record_channel_stop():
        shutdown_events.append("channels")

    worker_stop.side_effect = record_worker_stop
    stop_channel_service.side_effect = record_channel_stop
    worker_factory = MagicMock(return_value=worker_instance)

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _langgraph_with_scheduled_repos),
        patch("app.gateway.app._ensure_admin_user", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("app.gateway.app.auth.close_oidc_service", close_oidc_service),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.get_channel_service", side_effect=fake_get_channel_service),
        patch("app.channels.service.stop_channel_service", stop_channel_service),
        patch("deerflow.persistence.engine.get_session_factory", return_value=session_factory),
        patch("app.scheduler.ScheduledTaskService", return_value=scheduled_service),
        patch("app.scheduler.notification_delivery.NotificationDeliveryWorker", worker_factory),
        patch("deerflow.persistence.run.RunRepository"),
    ):
        async with lifespan(app):
            worker_on_app = getattr(app.state, "notification_delivery_worker", None)
        worker_instance.factory_kwargs = worker_factory.call_args.kwargs if worker_factory.call_args else None
        return worker_start, worker_stop, stop_channel_service, worker_on_app, shutdown_events, scheduled_service


def test_lifespan_skips_notification_worker_when_channel_service_missing(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.gateway.app")
    worker_start, worker_stop, stop_channel_service, worker_on_app, _shutdown_events, scheduled_service = asyncio.run(_run_lifespan_with_notification_worker(channel_service_available=False))

    worker_start.assert_not_awaited()
    assert worker_on_app is None
    assert any("write-only outbox" in record.message for record in caplog.records)
    # The enqueue side was wired with the scheduler; without delivery it is switched off again.
    scheduled_service.detach_notification_outbox.assert_called_once_with()
    stop_channel_service.assert_awaited_once()


def test_lifespan_starts_notification_worker_when_enqueue_and_channel_are_wired() -> None:
    worker_start, worker_stop, stop_channel_service, worker_on_app, shutdown_events, scheduled_service = asyncio.run(_run_lifespan_with_notification_worker(channel_service_available=True))

    worker_start.assert_awaited_once()
    assert worker_on_app is not None
    # The worker re-checks the target's connection at delivery time, so it
    # must be handed the connection repository's lookup, not left unwired.
    resolve_connections = worker_on_app.factory_kwargs["resolve_connections"]
    assert resolve_connections is not None
    assert getattr(resolve_connections, "__name__", None) == "list_connections"
    # Notices of owners without a UI language preference use channel_connections.notification_locale.
    assert worker_on_app.factory_kwargs["default_locale"] == "en-US"
    scheduled_service.detach_notification_outbox.assert_not_called()
    worker_stop.assert_awaited_once()
    stop_channel_service.assert_awaited_once()
    assert shutdown_events.index("worker") < shutdown_events.index("channels")


def test_lifespan_wires_notifications_after_the_channel_service_starts() -> None:
    # The lifespan starts the scheduler before the channel service (#5035), so the
    # outbox has to look the channel service up after that start.
    worker_start, worker_stop, _stop_channel_service, worker_on_app, _shutdown_events, scheduled_service = asyncio.run(_run_lifespan_with_notification_worker(channel_service_available=True, visible_only_after_start=True))

    worker_start.assert_awaited_once()
    assert worker_on_app is not None
    scheduled_service.detach_notification_outbox.assert_not_called()
    worker_stop.assert_awaited_once()


def test_lifespan_detaches_the_outbox_when_the_delivery_worker_cannot_start() -> None:
    from app.gateway.app import lifespan

    app = FastAPI()
    scheduled_service = MagicMock()
    scheduled_service.start = AsyncMock()
    scheduled_service.stop = AsyncMock()
    worker_instance = MagicMock()
    worker_instance.start = AsyncMock(side_effect=RuntimeError("worker cannot start"))
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})

    async def run() -> None:
        with (
            patch("app.gateway.app.get_app_config", return_value=_notification_startup_config()),
            patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
            patch("app.gateway.app.langgraph_runtime", _langgraph_with_scheduled_repos),
            patch("app.gateway.app._ensure_admin_user", AsyncMock()),
            patch("deerflow.skills.projection.ensure_public_skill_projection"),
            patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
            patch("app.channels.service.start_channel_service", AsyncMock(return_value=fake_service)),
            patch("app.channels.service.get_channel_service", return_value=fake_service),
            patch("app.channels.service.stop_channel_service", AsyncMock()),
            patch("deerflow.persistence.engine.get_session_factory", return_value=MagicMock()),
            patch("app.scheduler.ScheduledTaskService", return_value=scheduled_service),
            patch("app.scheduler.notification_delivery.NotificationDeliveryWorker", return_value=worker_instance),
            patch("deerflow.persistence.run.RunRepository"),
        ):
            async with lifespan(app):
                assert getattr(app.state, "notification_delivery_worker", None) is None

    asyncio.run(run())

    # Startup survives, and nothing keeps enqueueing rows that no worker would send.
    scheduled_service.detach_notification_outbox.assert_called_once_with()
