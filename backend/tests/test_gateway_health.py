"""Unit tests for the gateway readiness probe (app.gateway.health)."""

import sys
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


async def _constant_result(value: str) -> str:
    return value


def _patch_checkpointer_probe(monkeypatch, value: str) -> None:
    """Point the checkpointer probe at a canned result for payload tests."""
    monkeypatch.setattr(
        health_module,
        "_probe_checkpointer_backend",
        lambda: _constant_result(value),
    )


def _patch_checkpointer_config(monkeypatch, config: CheckpointerConfig | None) -> None:
    monkeypatch.setattr(health_module, "_effective_checkpointer_config", lambda: config)


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
async def test_readiness_payload_ready_when_database_ok(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())
    _patch_checkpointer_probe(monkeypatch, DATABASE_OK)

    status_code, payload = await readiness_payload()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == DATABASE_OK
    assert payload["checkpointer"] == DATABASE_OK


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_database_unreachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine(unreachable=True))
    _patch_checkpointer_probe(monkeypatch, DATABASE_OK)

    status_code, payload = await readiness_payload()

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == DATABASE_UNREACHABLE
    assert payload["checkpointer"] == DATABASE_OK


@pytest.mark.anyio
async def test_readiness_payload_ready_when_not_configured(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)
    _patch_checkpointer_probe(monkeypatch, DATABASE_NOT_CONFIGURED)

    status_code, payload = await readiness_payload()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == DATABASE_NOT_CONFIGURED
    assert payload["checkpointer"] == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_checkpointer_unreachable_but_database_ok(monkeypatch):
    """A healthy ORM engine must not mask an unreachable legacy checkpointer backend."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())
    _patch_checkpointer_probe(monkeypatch, DATABASE_UNREACHABLE)

    status_code, payload = await readiness_payload()

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == DATABASE_OK
    assert payload["checkpointer"] == DATABASE_UNREACHABLE


@pytest.mark.anyio
async def test_probe_checkpointer_memory_reports_not_configured(monkeypatch):
    _patch_checkpointer_config(monkeypatch, CheckpointerConfig(type="memory"))

    assert await _probe_checkpointer_backend() == DATABASE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_reachable(tmp_path, monkeypatch):
    _patch_checkpointer_config(
        monkeypatch,
        CheckpointerConfig(type="sqlite", connection_string=str(tmp_path / "checkpoints.db")),
    )

    assert await _probe_checkpointer_backend() == DATABASE_OK


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_unreachable(tmp_path, monkeypatch):
    missing_parent = tmp_path / "does-not-exist" / "checkpoints.db"
    _patch_checkpointer_config(
        monkeypatch,
        CheckpointerConfig(type="sqlite", connection_string=str(missing_parent)),
    )

    assert await _probe_checkpointer_backend() == DATABASE_UNREACHABLE


@pytest.mark.anyio
async def test_probe_checkpointer_postgres_without_psycopg_is_unreachable(monkeypatch):
    _patch_checkpointer_config(
        monkeypatch,
        CheckpointerConfig(
            type="postgres",
            connection_string="postgresql://user:pass@localhost:5432/deerflow",
        ),
    )
    monkeypatch.setitem(sys.modules, "psycopg", None)

    assert await _probe_checkpointer_backend() == DATABASE_UNREACHABLE
