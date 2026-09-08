"""Unit tests for the gateway readiness probe (app.gateway.health)."""

import asyncio
import pathlib
import sqlite3
import sys
import time
from contextlib import asynccontextmanager

import pytest

import app.gateway.health as health_module
from app.gateway.health import (
    DATABASE_NOT_CONFIGURED,
    DATABASE_OK,
    DATABASE_UNREACHABLE,
    _probe_checkpointer_backend,
    check_database_health,
    readiness_payload,
    resolve_checkpointer_config,
)
from deerflow.config.checkpointer_config import CheckpointerConfig


class _FakeConnection:
    async def execute(self, *args, **kwargs):
        return None


class _FakeEngine:
    def __init__(self, *, unreachable: bool = False):
        self._unreachable = unreachable

    def connect(self):
        @asynccontextmanager
        async def _connect():
            if self._unreachable:
                raise RuntimeError("database is down")
            yield _FakeConnection()

        return _connect()


def _create_sqlite_file(path: pathlib.Path) -> None:
    """Create a valid (empty) SQLite database file at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(path)).close()


@pytest.mark.anyio
async def test_check_database_health_without_engine(monkeypatch):
    """backend=memory (no engine) must report not_configured, never unreachable."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)

    assert await check_database_health() == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_check_database_health_reachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    assert await check_database_health() == DATABASE_OK


@pytest.mark.anyio
async def test_check_database_health_unreachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine(unreachable=True))

    assert await check_database_health() == DATABASE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_payload_ready_when_database_ok_and_memory_backend(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"))

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == DATABASE_OK
    assert payload["checkpointer"] == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_database_unreachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine(unreachable=True))

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"))

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == DATABASE_UNREACHABLE
    assert payload["checkpointer"] == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_ready_when_nothing_configured(monkeypatch):
    """backend=memory end to end must stay ready with not_configured results."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"))

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == DATABASE_NOT_CONFIGURED
    assert payload["checkpointer"] == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_checkpointer_unreachable_but_database_ok(tmp_path, monkeypatch):
    """A healthy ORM engine must not mask an unreachable legacy checkpointer backend."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())
    config = CheckpointerConfig(type="sqlite", connection_string=str(tmp_path / "missing" / "checkpoints.db"))

    status_code, payload = await readiness_payload(config)

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == DATABASE_OK
    assert payload["checkpointer"] == DATABASE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_payload_fails_closed_without_startup_snapshot(monkeypatch):
    """No startup config snapshot must degrade readiness, never report ready."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    status_code, payload = await readiness_payload(None)

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == DATABASE_OK
    assert payload["checkpointer"] == DATABASE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_probes_run_concurrently(monkeypatch):
    """Slow-but-healthy probes must not add their budgets together."""

    async def _slow_ok(*args) -> str:
        await asyncio.sleep(0.35)
        return DATABASE_OK

    monkeypatch.setattr(health_module, "check_database_health", _slow_ok)
    monkeypatch.setattr(health_module, "_probe_checkpointer_backend", _slow_ok)

    started = time.perf_counter()
    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"))
    elapsed = time.perf_counter() - started

    assert status_code == 200
    assert payload["database"] == DATABASE_OK
    assert payload["checkpointer"] == DATABASE_OK
    # Two sequential 0.35s probes would take ~0.7s; concurrent ones finish
    # within a single probe window.
    assert elapsed < 0.6


@pytest.mark.anyio
async def test_readiness_payload_enforces_endpoint_deadline(monkeypatch):
    """A probe ignoring its own budget must trip the endpoint-wide deadline."""

    async def _hanging(*args) -> str:
        await asyncio.sleep(30)
        return DATABASE_OK

    monkeypatch.setattr(health_module, "check_database_health", _hanging)
    monkeypatch.setattr(health_module, "_probe_checkpointer_backend", _hanging)
    monkeypatch.setattr(health_module, "_READINESS_DEADLINE_SECONDS", 0.05)

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"))

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == DATABASE_UNREACHABLE
    assert payload["checkpointer"] == DATABASE_UNREACHABLE


@pytest.mark.anyio
async def test_concurrent_readiness_requests_do_not_open_concurrent_probe_connections(monkeypatch):
    """Public /health/ready must serialize connection-opening probes.

    An unauthenticated thundering herd must never translate into an unbounded
    number of new database connections (e.g. past PostgreSQL
    max_connections): at most one probe connection may be in flight at a time
    per process.
    """
    active = 0
    max_active = 0

    async def _tracked_probe(conn_string: str | None) -> str:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.05)
            return DATABASE_OK
        finally:
            active -= 1

    monkeypatch.setattr(health_module, "_probe_sqlite_backend", _tracked_probe)
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)
    config = CheckpointerConfig(type="sqlite", connection_string=":memory:")

    results = await asyncio.gather(*(readiness_payload(config) for _ in range(8)))

    assert [status_code for status_code, _ in results] == [200] * 8
    assert max_active == 1


@pytest.mark.anyio
async def test_probe_checkpointer_memory_reports_not_configured():
    assert await _probe_checkpointer_backend(CheckpointerConfig(type="memory")) == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_reachable(tmp_path):
    db_path = tmp_path / "checkpoints.db"
    _create_sqlite_file(db_path)

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=str(db_path)))

    assert result == DATABASE_OK


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_file_uri_reachable(tmp_path):
    db_path = tmp_path / "checkpoints.db"
    _create_sqlite_file(db_path)

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=pathlib.Path(db_path).as_uri()))

    assert result == DATABASE_OK


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_missing_file_stays_missing_and_unreachable(tmp_path):
    """The probe must never create a missing SQLite file (regression)."""
    missing = tmp_path / "checkpoints.db"

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=str(missing)))

    assert result == DATABASE_UNREACHABLE
    assert not missing.exists()


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_unreachable_when_parent_missing(tmp_path):
    missing_parent = tmp_path / "does-not-exist" / "checkpoints.db"

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=str(missing_parent)))

    assert result == DATABASE_UNREACHABLE


@pytest.mark.anyio
@pytest.mark.parametrize(
    "conn_string",
    [":memory:", "file:memdb1?mode=memory&cache=shared", "file::memory:?cache=shared"],
)
async def test_probe_checkpointer_sqlite_in_memory_is_not_configured(conn_string):
    """In-memory SQLite has no external state, mirroring the memory backend."""
    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=conn_string))

    assert result == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_probe_checkpointer_postgres_without_psycopg_is_unreachable(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)

    result = await _probe_checkpointer_backend(
        CheckpointerConfig(
            type="postgres",
            connection_string="postgresql://user:pass@localhost:5432/deerflow",
        )
    )

    assert result == DATABASE_UNREACHABLE


def test_resolve_checkpointer_config_passes_through_resolution(monkeypatch):
    resolved = CheckpointerConfig(type="memory")
    monkeypatch.setattr(
        "deerflow.runtime.checkpointer.provider._resolve_checkpointer_config",
        lambda app_config: resolved,
    )

    assert resolve_checkpointer_config(object()) is resolved


def test_resolve_checkpointer_config_failure_fails_closed(monkeypatch):
    """A resolution failure must surface as None, never as a memory default."""

    def _raise(app_config):
        raise RuntimeError("broken checkpointer config")

    monkeypatch.setattr(
        "deerflow.runtime.checkpointer.provider._resolve_checkpointer_config",
        _raise,
    )

    assert resolve_checkpointer_config(object()) is None
