"""Tests for the multi-worker Postgres startup gate.

Pins the contract documented in ``docs/multi_worker.md`` work item 1
(issue #3948): when ``GATEWAY_WORKERS > 1`` and the configured
database backend is not Postgres, the Gateway must refuse to start.
The gate runs inside :func:`langgraph_runtime` *before* any
persistence engine is initialised so operators see a clear error
instead of intermittent SQLite ``database is locked`` failures in
production.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.gateway.deps import _enforce_postgres_for_multi_worker, langgraph_runtime
from app.gateway.routers.browser import _browser_tools_enabled
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.run_ownership_config import RunOwnershipConfig


def _config_with_backend(backend: str, *, heartbeat_enabled: bool | None = None, browser_enabled: bool = False) -> SimpleNamespace:
    run_ownership = RunOwnershipConfig(heartbeat_enabled=heartbeat_enabled) if heartbeat_enabled is not None else None
    tools = [SimpleNamespace(name="browser_navigate")] if browser_enabled else []
    return SimpleNamespace(database=DatabaseConfig(backend=backend), run_ownership=run_ownership, tools=tools)


# ---------------------------------------------------------------------------
# Unit tests of the gate function itself
# ---------------------------------------------------------------------------


def test_gate_noop_when_gateway_workers_unset(monkeypatch):
    """With GATEWAY_WORKERS unset, every backend must be accepted."""
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


def test_gate_noop_for_single_worker(monkeypatch):
    """GATEWAY_WORKERS=1 preserves the historical single-worker behavior."""
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


def test_gate_allows_multi_worker_with_postgres_and_heartbeat(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=True))


def test_gate_rejects_process_local_browser_with_multi_worker(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(
            _config_with_backend("postgres", heartbeat_enabled=True, browser_enabled=True),
        )
    msg = str(exc_info.value)
    assert "process-local" in msg
    assert "GATEWAY_WORKERS=1" in msg


def test_runtime_browser_surface_stays_disabled_after_incompatible_hot_reload(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    live_config = SimpleNamespace(tools=[SimpleNamespace(name="browser_navigate", model_extra={})])

    with patch("deerflow.config.get_app_config", return_value=live_config):
        assert _browser_tools_enabled() is False


def test_gate_rejects_multi_worker_with_sqlite(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=2" in msg
    assert "postgres" in msg.lower()
    assert "sqlite" in msg.lower()


def test_gate_rejects_multi_worker_with_memory(monkeypatch):
    """The gate is not sqlite-specific: memory is also unsafe across processes."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit):
        _enforce_postgres_for_multi_worker(_config_with_backend("memory"))


def test_gate_rejects_high_worker_counts(monkeypatch):
    """The threshold is >1, not ==2; prod-scale counts must also be gated."""
    monkeypatch.setenv("GATEWAY_WORKERS", "4")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    assert "GATEWAY_WORKERS=4" in str(exc_info.value)


def test_gate_treats_invalid_env_as_single_worker(monkeypatch):
    """Non-integer GATEWAY_WORKERS values must not crash startup.

    Uvicorn itself rejects these later; the gate should not preempt
    that with its own crash. Falling back to 1 keeps the gate inert.
    """
    for invalid in ("", "auto", "1.5", "abc", "0x4"):
        monkeypatch.setenv("GATEWAY_WORKERS", invalid)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_treats_zero_and_negatives_as_single_worker(monkeypatch):
    """GATEWAY_WORKERS <= 1 (including 0 and negatives) skips the gate."""
    for value in ("0", "-1", "-999"):
        monkeypatch.setenv("GATEWAY_WORKERS", value)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_error_message_lists_both_remediations(monkeypatch):
    """Operators must see both fix options without reading docs."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=1" in msg, "must mention the rollback knob"
    assert "Postgres" in msg, "must mention the alternative backend"


# ---------------------------------------------------------------------------
# Heartbeat enforcement: multi-worker requires heartbeat_enabled=true
# ---------------------------------------------------------------------------


def test_gate_rejects_multi_worker_without_heartbeat(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=False))
    msg = str(exc_info.value)
    assert "heartbeat_enabled=true" in msg


def test_gate_rejects_multi_worker_without_run_ownership_config(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=None))
    msg = str(exc_info.value)
    assert "heartbeat_enabled=true" in msg


def test_gate_heartbeat_check_not_triggered_for_single_worker(monkeypatch):
    """GATEWAY_WORKERS=1 skips the heartbeat check entirely."""
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=False))


def test_gate_heartbeat_check_not_triggered_for_sqlite(monkeypatch):
    """The gate exits on Postgres check before reaching heartbeat check."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", heartbeat_enabled=True))
    msg = str(exc_info.value)
    assert "postgres" in msg.lower()


# ---------------------------------------------------------------------------
# Integration: the gate is wired into langgraph_runtime before init_engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_langgraph_runtime_invokes_gate_before_persistence_setup(monkeypatch):
    """When the gate trips, no persistence / stream-bridge setup may run.

    Guards against regressions that reorder the gate behind
    ``init_engine_from_config`` (or any other expensive startup step).
    """
    monkeypatch.setenv("GATEWAY_WORKERS", "2")

    init_engine_from_config = AsyncMock(name="init_engine_from_config")

    @asynccontextmanager
    async def _noop_stream_bridge(_config):
        yield MagicMock()

    with (
        patch(
            "deerflow.persistence.engine.init_engine_from_config",
            init_engine_from_config,
        ),
        patch("deerflow.runtime.make_stream_bridge", side_effect=_noop_stream_bridge) as make_stream_bridge,
        patch("deerflow.runtime.make_store", side_effect=_noop_stream_bridge) as make_store,
    ):
        app = FastAPI()
        startup_config = _config_with_backend("sqlite")
        with pytest.raises(SystemExit):
            async with langgraph_runtime(app, startup_config):
                pass

    init_engine_from_config.assert_not_called()
    make_stream_bridge.assert_not_called()
    make_store.assert_not_called()
