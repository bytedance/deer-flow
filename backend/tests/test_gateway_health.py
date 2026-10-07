"""Unit tests for the gateway readiness probe (app.gateway.health)."""

import asyncio
import pathlib
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import app.gateway.health as health_module
from app.gateway.health import (
    PROBE_NOT_CONFIGURED,
    PROBE_OK,
    PROBE_UNREACHABLE,
    READINESS_CHECKPOINTER_CONFIG_ATTR,
    READINESS_PROVISIONER_URL_ATTR,
    _probe_checkpointer_backend,
    _probe_provisioner,
    _probe_stream_bridge,
    check_database_health,
    readiness_payload,
    resolve_checkpointer_config,
    resolve_provisioner_url,
)
from deerflow.config.checkpointer_config import CheckpointerConfig
from deerflow.runtime import MemoryStreamBridge


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


class _FakeCrossProcessBridge(MemoryStreamBridge):
    """Bridge with an external backend whose ``ping`` answer is scripted."""

    supports_cross_process = True

    def __init__(self, *, result: bool = True, error: Exception | None = None, delay: float = 0.0) -> None:
        super().__init__()
        self._result = result
        self._error = error
        self._delay = delay
        self.ping_calls = 0

    async def ping(self) -> bool:
        self.ping_calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._result


def _provisioner_client_factory(handler):
    """Return a ``_make_provisioner_client`` replacement backed by ``httpx.MockTransport``."""

    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return _factory


def _install_provisioner(monkeypatch, handler) -> None:
    monkeypatch.setattr(health_module, "_make_provisioner_client", _provisioner_client_factory(handler))


@pytest.mark.anyio
async def test_check_database_health_without_engine(monkeypatch):
    """backend=memory (no engine) must report not_configured, never unreachable."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)

    assert await check_database_health() == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_check_database_health_reachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    assert await check_database_health() == PROBE_OK


@pytest.mark.anyio
async def test_check_database_health_unreachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine(unreachable=True))

    assert await check_database_health() == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_payload_ready_when_database_ok_and_memory_backend(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"), stream_bridge=MemoryStreamBridge())

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == PROBE_OK
    assert payload["checkpointer"] == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_database_unreachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine(unreachable=True))

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"), stream_bridge=MemoryStreamBridge())

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == PROBE_UNREACHABLE
    assert payload["checkpointer"] == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_ready_when_nothing_configured(monkeypatch):
    """backend=memory end to end must stay ready with not_configured results."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"), stream_bridge=MemoryStreamBridge())

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == PROBE_NOT_CONFIGURED
    assert payload["checkpointer"] == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_checkpointer_unreachable_but_database_ok(tmp_path, monkeypatch):
    """A healthy ORM engine must not mask an unreachable legacy checkpointer backend."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())
    config = CheckpointerConfig(type="sqlite", connection_string=str(tmp_path / "missing" / "checkpoints.db"))

    status_code, payload = await readiness_payload(config, stream_bridge=MemoryStreamBridge())

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == PROBE_OK
    assert payload["checkpointer"] == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_payload_fails_closed_without_startup_snapshot(monkeypatch):
    """No startup config snapshot must degrade readiness, never report ready."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    status_code, payload = await readiness_payload(None, stream_bridge=MemoryStreamBridge())

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == PROBE_OK
    assert payload["checkpointer"] == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_probes_run_concurrently(monkeypatch):
    """Slow-but-healthy probes must not add their budgets together."""

    async def _slow_ok(*args) -> str:
        await asyncio.sleep(0.35)
        return PROBE_OK

    monkeypatch.setattr(health_module, "check_database_health", _slow_ok)
    monkeypatch.setattr(health_module, "_probe_checkpointer_backend", _slow_ok)
    monkeypatch.setattr(health_module, "_probe_provisioner", _slow_ok)

    started = time.perf_counter()
    status_code, payload = await readiness_payload(
        CheckpointerConfig(type="memory"),
        stream_bridge=_FakeCrossProcessBridge(delay=0.35),
        provisioner_url="http://provisioner:8002",
    )
    elapsed = time.perf_counter() - started

    assert status_code == 200
    assert payload["database"] == PROBE_OK
    assert payload["checkpointer"] == PROBE_OK
    assert payload["stream_bridge"] == PROBE_OK
    assert payload["provisioner"] == PROBE_OK
    # Four sequential 0.35s probes would take ~1.4s; concurrent ones finish
    # within a single probe window.
    assert elapsed < 0.6


@pytest.mark.anyio
async def test_readiness_payload_enforces_endpoint_deadline(monkeypatch):
    """A probe ignoring its own budget must trip the endpoint-wide deadline."""

    async def _hanging(*args) -> str:
        await asyncio.sleep(30)
        return PROBE_OK

    monkeypatch.setattr(health_module, "check_database_health", _hanging)
    monkeypatch.setattr(health_module, "_probe_checkpointer_backend", _hanging)
    monkeypatch.setattr(health_module, "_READINESS_DEADLINE_SECONDS", 0.05)

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"), stream_bridge=MemoryStreamBridge())

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == PROBE_UNREACHABLE
    assert payload["checkpointer"] == PROBE_UNREACHABLE


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
            return PROBE_OK
        finally:
            active -= 1

    monkeypatch.setattr(health_module, "_probe_sqlite_backend", _tracked_probe)
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: None)
    config = CheckpointerConfig(type="sqlite", connection_string=":memory:")

    results = await asyncio.gather(*(readiness_payload(config, stream_bridge=MemoryStreamBridge()) for _ in range(8)))

    assert [status_code for status_code, _ in results] == [200] * 8
    assert max_active == 1


@pytest.mark.anyio
async def test_probe_checkpointer_memory_reports_not_configured():
    assert await _probe_checkpointer_backend(CheckpointerConfig(type="memory")) == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_reachable(tmp_path):
    db_path = tmp_path / "checkpoints.db"
    _create_sqlite_file(db_path)

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=str(db_path)))

    assert result == PROBE_OK


@pytest.mark.anyio
@pytest.mark.parametrize(
    "conn_string",
    ["file:checkpoints.db", "file::memory:?cache=shared", "file:memdb1?mode=memory&cache=shared"],
)
async def test_probe_checkpointer_sqlite_uri_is_unreachable(conn_string, tmp_path, monkeypatch):
    """The runtime refuses SQLite URIs, so the probe must not report them healthy."""
    monkeypatch.chdir(tmp_path)
    _create_sqlite_file(tmp_path / "checkpoints.db")

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=conn_string))

    assert result == PROBE_UNREACHABLE
    assert [path.name for path in tmp_path.iterdir()] == ["checkpoints.db"]


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_missing_file_stays_missing_and_unreachable(tmp_path):
    """The probe must never create a missing SQLite file (regression)."""
    missing = tmp_path / "checkpoints.db"

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=str(missing)))

    assert result == PROBE_UNREACHABLE
    assert not missing.exists()


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_unreachable_when_parent_missing(tmp_path):
    missing_parent = tmp_path / "does-not-exist" / "checkpoints.db"

    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=str(missing_parent)))

    assert result == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_probe_checkpointer_sqlite_in_memory_is_not_configured():
    """In-memory SQLite has no external state, mirroring the memory backend."""
    result = await _probe_checkpointer_backend(CheckpointerConfig(type="sqlite", connection_string=":memory:"))

    assert result == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_probe_checkpointer_postgres_without_psycopg_is_unreachable(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)

    result = await _probe_checkpointer_backend(
        CheckpointerConfig(
            type="postgres",
            connection_string="postgresql://user:pass@localhost:5432/deerflow",
        )
    )

    assert result == PROBE_UNREACHABLE


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


class _BlockingProbeConnection:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()
        self.close_finished = asyncio.Event()

    async def execute(self, *_args, **_kwargs):
        return None

    async def close(self) -> None:
        self.close_started.set()
        await self.allow_close.wait()
        self.close_finished.set()


async def _assert_probe_close_is_drained(probe_coro, connection: _BlockingProbeConnection, label: str) -> None:
    probe = asyncio.create_task(probe_coro)
    try:
        await asyncio.wait_for(connection.close_started.wait(), 1)

        probe.cancel("first cancellation")
        await asyncio.sleep(0)
        probe.cancel("second cancellation")
        for _ in range(5):
            await asyncio.sleep(0)

        assert not probe.done(), f"readiness probe returned before its {label} connection closed"

        connection.allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await probe
        assert connection.close_finished.is_set()
    finally:
        connection.allow_close.set()
        await asyncio.gather(probe, return_exceptions=True)


@pytest.mark.anyio
async def test_sqlite_probe_drains_connection_close_across_repeated_cancellation(monkeypatch):
    import aiosqlite

    connection = _BlockingProbeConnection()

    async def fake_connect(*_args, **_kwargs):
        return connection

    monkeypatch.setattr(aiosqlite, "connect", fake_connect)

    await _assert_probe_close_is_drained(
        health_module._probe_sqlite_backend("/tmp/deerflow-health-probe.db"),
        connection,
        "SQLite",
    )


class _FakeProbeCursor:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        return None


class _BlockingPostgresProbeConnection(_BlockingProbeConnection):
    def cursor(self):
        return _FakeProbeCursor()


@pytest.mark.anyio
async def test_postgres_probe_drains_connection_close_across_repeated_cancellation(monkeypatch):
    import types

    connection = _BlockingPostgresProbeConnection()

    class FakeAsyncConnection:
        @classmethod
        async def connect(cls, *_args, **_kwargs):
            return connection

    fake_psycopg = types.ModuleType("psycopg")
    fake_psycopg.AsyncConnection = FakeAsyncConnection
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    await _assert_probe_close_is_drained(
        health_module._probe_postgres_backend(
            "postgresql://user:pass@localhost:5432/deerflow",
            "",
        ),
        connection,
        "PostgreSQL",
    )


# ---------------------------------------------------------------------------
# Stream bridge probe
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_probe_stream_bridge_memory_reports_not_configured():
    """The process-local memory bridge has no external backend to probe."""
    bridge = MemoryStreamBridge()

    assert await _probe_stream_bridge(bridge) == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_probe_stream_bridge_reachable_backend_is_ok():
    bridge = _FakeCrossProcessBridge(result=True)

    assert await _probe_stream_bridge(bridge) == PROBE_OK
    assert bridge.ping_calls == 1


@pytest.mark.anyio
async def test_probe_stream_bridge_false_ping_is_unreachable():
    assert await _probe_stream_bridge(_FakeCrossProcessBridge(result=False)) == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_probe_stream_bridge_raising_ping_is_unreachable():
    assert await _probe_stream_bridge(_FakeCrossProcessBridge(error=RuntimeError("redis exploded"))) == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_probe_stream_bridge_enforces_probe_timeout(monkeypatch):
    """A ping that never answers must be bounded by the per-probe budget."""
    monkeypatch.setattr(health_module, "_PROBE_TIMEOUT_SECONDS", 0.05)

    started = time.perf_counter()
    result = await _probe_stream_bridge(_FakeCrossProcessBridge(delay=30))
    elapsed = time.perf_counter() - started

    assert result == PROBE_UNREACHABLE
    assert elapsed < 1.0


@pytest.mark.anyio
async def test_probe_stream_bridge_fails_closed_without_bridge():
    """No bridge on app.state means runs cannot stream: never report ready."""
    assert await _probe_stream_bridge(None) == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_concurrent_stream_bridge_probes_are_serialized():
    """Public /health/ready must not fan a thundering herd out onto the Redis pool."""
    active = 0
    max_active = 0

    class _TrackingBridge(_FakeCrossProcessBridge):
        async def ping(self) -> bool:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.02)
                return True
            finally:
                active -= 1

    bridge = _TrackingBridge()
    results = await asyncio.gather(*(_probe_stream_bridge(bridge) for _ in range(6)))

    assert results == [PROBE_OK] * 6
    assert max_active == 1


# ---------------------------------------------------------------------------
# Provisioner probe
# ---------------------------------------------------------------------------


def test_resolve_provisioner_url_normalises_configured_url():
    config = SimpleNamespace(sandbox=SimpleNamespace(provisioner_url=" http://provisioner:8002/ "))

    assert resolve_provisioner_url(config) == "http://provisioner:8002"


@pytest.mark.parametrize(
    "config",
    [
        SimpleNamespace(sandbox=SimpleNamespace()),
        SimpleNamespace(sandbox=SimpleNamespace(provisioner_url=None)),
        SimpleNamespace(sandbox=SimpleNamespace(provisioner_url="   ")),
        SimpleNamespace(sandbox=None),
        SimpleNamespace(),
    ],
    ids=["no-field", "none", "blank", "no-sandbox", "no-sandbox-attr"],
)
def test_resolve_provisioner_url_absent(config):
    assert resolve_provisioner_url(config) is None


@pytest.mark.anyio
async def test_probe_provisioner_not_configured_without_url():
    assert await _probe_provisioner(None) == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_probe_provisioner_calls_unauthenticated_health_route(monkeypatch):
    """The probe targets the provisioner's own GET /health, which needs no API key."""
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    _install_provisioner(monkeypatch, _handler)

    assert await _probe_provisioner("http://provisioner:8002") == PROBE_OK
    assert [str(request.url) for request in seen] == ["http://provisioner:8002/health"]
    assert "x-api-key" not in {name.lower() for name in seen[0].headers}


@pytest.mark.anyio
async def test_probe_provisioner_non_200_is_unreachable(monkeypatch):
    _install_provisioner(monkeypatch, lambda request: httpx.Response(503, text="draining"))

    assert await _probe_provisioner("http://provisioner:8002") == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_probe_provisioner_connection_error_is_unreachable(monkeypatch):
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_provisioner(monkeypatch, _handler)

    assert await _probe_provisioner("http://provisioner:8002") == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_probe_provisioner_enforces_probe_timeout(monkeypatch):
    monkeypatch.setattr(health_module, "_PROBE_TIMEOUT_SECONDS", 0.05)

    async def _hanging_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200)

    _install_provisioner(monkeypatch, _hanging_handler)

    started = time.perf_counter()
    result = await _probe_provisioner("http://provisioner:8002")
    elapsed = time.perf_counter() - started

    assert result == PROBE_UNREACHABLE
    assert elapsed < 1.0


@pytest.mark.anyio
async def test_concurrent_provisioner_probes_are_serialized(monkeypatch):
    """Public /health/ready must not amplify into a connection flood at the provisioner."""
    active = 0
    max_active = 0

    async def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.02)
            return httpx.Response(200)
        finally:
            active -= 1

    _install_provisioner(monkeypatch, _handler)

    results = await asyncio.gather(*(_probe_provisioner("http://provisioner:8002") for _ in range(6)))

    assert results == [PROBE_OK] * 6
    assert max_active == 1


# ---------------------------------------------------------------------------
# readiness_payload: stream bridge and provisioner verdicts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_readiness_payload_degraded_when_stream_bridge_unreachable(monkeypatch):
    """Redis down means no run can publish, stream or be cancelled: the pod is not ready."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"), stream_bridge=_FakeCrossProcessBridge(result=False))

    assert status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == PROBE_OK
    assert payload["checkpointer"] == PROBE_NOT_CONFIGURED
    assert payload["stream_bridge"] == PROBE_UNREACHABLE
    assert payload["provisioner"] == PROBE_NOT_CONFIGURED


@pytest.mark.anyio
async def test_readiness_payload_ready_when_stream_bridge_reachable(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"), stream_bridge=_FakeCrossProcessBridge(result=True))

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["stream_bridge"] == PROBE_OK


@pytest.mark.anyio
async def test_readiness_payload_fails_closed_without_stream_bridge(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    status_code, payload = await readiness_payload(CheckpointerConfig(type="memory"), stream_bridge=None)

    assert status_code == 503
    assert payload["stream_bridge"] == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_payload_reports_unreachable_provisioner_without_degrading(monkeypatch):
    """Every replica shares one provisioner; its blip must not take the whole service out."""
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())
    _install_provisioner(monkeypatch, lambda request: httpx.Response(503))

    status_code, payload = await readiness_payload(
        CheckpointerConfig(type="memory"),
        stream_bridge=MemoryStreamBridge(),
        provisioner_url="http://provisioner:8002",
    )

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["provisioner"] == PROBE_UNREACHABLE


@pytest.mark.anyio
async def test_readiness_payload_reports_reachable_provisioner(monkeypatch):
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())
    _install_provisioner(monkeypatch, lambda request: httpx.Response(200, json={"status": "ok"}))

    status_code, payload = await readiness_payload(
        CheckpointerConfig(type="memory"),
        stream_bridge=MemoryStreamBridge(),
        provisioner_url="http://provisioner:8002",
    )

    assert status_code == 200
    assert payload["provisioner"] == PROBE_OK


@pytest.mark.anyio
async def test_readiness_deadline_only_fails_the_probes_that_overran(monkeypatch):
    """A probe that ignores its budget must not erase the verdicts of the probes that finished.

    Otherwise a wedged report-only provisioner probe would flip the whole
    endpoint to 503 through the deadline path.
    """
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())

    async def _hanging(*args) -> str:
        await asyncio.sleep(30)
        return PROBE_OK

    monkeypatch.setattr(health_module, "_probe_provisioner", _hanging)
    monkeypatch.setattr(health_module, "_READINESS_DEADLINE_SECONDS", 0.1)

    status_code, payload = await readiness_payload(
        CheckpointerConfig(type="memory"),
        stream_bridge=MemoryStreamBridge(),
        provisioner_url="http://provisioner:8002",
    )

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["database"] == PROBE_OK
    assert payload["checkpointer"] == PROBE_NOT_CONFIGURED
    assert payload["stream_bridge"] == PROBE_NOT_CONFIGURED
    assert payload["provisioner"] == PROBE_UNREACHABLE


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------


def _ready_client(monkeypatch, *, stream_bridge, provisioner_url: str | None) -> TestClient:
    """Build the real gateway app and wire the startup state the probe reads.

    The lifespan is deliberately not run: the test pins the ``app.state``
    contract the route depends on instead of booting persistence.
    """
    from app.gateway.app import create_app

    app = create_app()
    setattr(app.state, READINESS_CHECKPOINTER_CONFIG_ATTR, CheckpointerConfig(type="memory"))
    setattr(app.state, READINESS_PROVISIONER_URL_ATTR, provisioner_url)
    app.state.stream_bridge = stream_bridge
    monkeypatch.setattr("app.gateway.health.get_engine", lambda: _FakeEngine())
    return TestClient(app)


def test_health_ready_route_reports_every_dependency(monkeypatch):
    _install_provisioner(monkeypatch, lambda request: httpx.Response(200, json={"status": "ok"}))
    client = _ready_client(monkeypatch, stream_bridge=_FakeCrossProcessBridge(result=True), provisioner_url="http://provisioner:8002")

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "deer-flow-gateway",
        "database": PROBE_OK,
        "checkpointer": PROBE_NOT_CONFIGURED,
        "stream_bridge": PROBE_OK,
        "provisioner": PROBE_OK,
    }


def test_health_ready_route_returns_503_when_stream_bridge_unreachable(monkeypatch):
    client = _ready_client(monkeypatch, stream_bridge=_FakeCrossProcessBridge(result=False), provisioner_url=None)

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["stream_bridge"] == PROBE_UNREACHABLE
    assert body["provisioner"] == PROBE_NOT_CONFIGURED


def test_health_ready_route_keeps_200_when_only_provisioner_is_down(monkeypatch):
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_provisioner(monkeypatch, _handler)
    client = _ready_client(monkeypatch, stream_bridge=MemoryStreamBridge(), provisioner_url="http://provisioner:8002")

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["provisioner"] == PROBE_UNREACHABLE
