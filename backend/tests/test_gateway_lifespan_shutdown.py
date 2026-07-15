"""Regression tests for Gateway lifespan shutdown.

These tests guard the invariant that lifespan shutdown is *bounded*: a
misbehaving channel whose ``stop()`` blocks forever must not keep the
uvicorn worker alive. A hung worker is the precondition for the
signal-reentrancy deadlock described in
``app.gateway.app._SHUTDOWN_HOOK_TIMEOUT_SECONDS``.
"""

from __future__ import annotations

import asyncio
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
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})

    async def fake_start(_startup_config):
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
    startup_config = SimpleNamespace(log_level="INFO", memory=SimpleNamespace(token_counting="char"))
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})
    cleanup_upload_staging_files = MagicMock(return_value=2)
    close_oidc_service = AsyncMock()
    stop_channel_service = AsyncMock()

    async def fake_start(_startup_config):
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
