"""Unit tests for the gateway readiness probe (app.gateway.health)."""

from contextlib import asynccontextmanager

import pytest

from app.gateway.health import (
    DATABASE_NOT_CONFIGURED,
    DATABASE_OK,
    DATABASE_UNREACHABLE,
    check_database_health,
    readiness_payload,
)


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

    status_code, payload = await readiness_payload()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == DATABASE_OK


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_database_unreachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine(unreachable=True))

    status_code, payload = await readiness_payload()

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == DATABASE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_payload_ready_when_not_configured(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)

    status_code, payload = await readiness_payload()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == DATABASE_NOT_CONFIGURED
