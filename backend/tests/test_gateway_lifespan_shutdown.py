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


async def _run_lifespan_with_memory_flush(*, enabled: bool, flush_return: bool | Exception) -> MagicMock:
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
    else:
        manager.shutdown_flush.return_value = flush_return

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


def test_lifespan_drains_memory_on_shutdown_with_configured_timeout(caplog) -> None:
    """When memory is enabled, shutdown calls manager.shutdown_flush with the
    configured timeout (asserts the timeout is forwarded, review #3) and logs
    'completed' at INFO when the drain finishes."""
    caplog.set_level(logging.INFO, logger="app.gateway.app")
    manager = asyncio.run(_run_lifespan_with_memory_flush(enabled=True, flush_return=True))
    manager.shutdown_flush.assert_called_once_with(5.0)
    assert any(r.levelno == logging.INFO and "flush completed" in r.message for r in caplog.records)


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
