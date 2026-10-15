"""Readiness probe helpers for the gateway health endpoints.

``GET /health`` stays a pure liveness signal: 200 whenever the process is up.
``GET /health/ready`` additionally probes the backends the gateway actually
depends on, so orchestrators (Docker healthchecks, Kubernetes probes) treat the
gateway as ready only when agent runs can be persisted and streamed. Three
probes gate the verdict and can be configured independently:

* the ORM engine behind ``database:`` (application repositories),
* the effective LangGraph checkpointer/Store backend - the legacy
  ``checkpointer:`` section when present, otherwise derived from ``database:``
  (memory/sqlite/postgres), and
* the stream bridge's external backend (Redis for ``stream_bridge.type:
  redis``). Its client connects lazily, so without this ping a gateway whose
  Redis is down starts, reports ready and then fails every run's publish.

A fourth probe is report-only: when ``sandbox.provisioner_url`` is set, the
provisioner's own unauthenticated ``GET /health`` is checked and its verdict
is included in the body, but it never flips the endpoint to 503. Every
replica shares one provisioner, so a blip there must not drain the service.

All probes run concurrently beneath a single endpoint-wide deadline
(:data:`_READINESS_DEADLINE_SECONDS`), so normal probe work completes within
one probe window rather than the sum of the budgets. A probe that overruns the
deadline fails alone; verdicts already collected are kept. Connection teardown
is ownership-critical and is drained to completion after cancellation, so a
stalled close may outlive the probe/deadline budget. Probe targets are
resolved once at startup from the same snapshot ``langgraph_runtime`` builds
its resources from and are stored on ``app.state``; probing a hot-reloaded
config instead could check a backend the running process is not using. A
process-local backend (``memory``) has nothing to probe and reports
``not_configured``; a startup target that cannot be resolved fails closed as
unreachable. Connection-opening probes are serialized behind strict
per-process gates, one per probe kind: the route is public through the
``/health`` auth prefix, so unlimited concurrent requests must never translate
into unlimited new PostgreSQL connections, Redis pool growth or a connection
flood at the provisioner.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import weakref
from collections.abc import Awaitable
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import text

from deerflow.persistence.engine import get_engine
from deerflow.utils.file_io import await_drained

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.checkpointer_config import CheckpointerConfig
    from deerflow.runtime.stream_bridge import StreamBridge

logger = logging.getLogger(__name__)

# Upper bound for connection/open/query work in a single probe attempt. Cleanup
# is ownership-critical: once a probe owns a connection, close is drained even
# if this timeout expires, so a stalled teardown may outlive this bound.
_PROBE_TIMEOUT_SECONDS = 2.0

# Whole-endpoint deadline for ordinary probe work. They run concurrently, so a
# healthy response normally completes within a single probe window; the extra
# margin absorbs scheduling/cancellation overhead. Owned connection teardown is
# intentionally exempt: ``await_drained`` defers cancellation until close
# finishes, so a wedged close can outlive this deadline while preserving
# resource ownership. Waiting requests are still shed by their own deadline.
# Orchestrator timeouts should therefore exceed this bound and may still fire
# first if teardown itself stalls.
_READINESS_DEADLINE_SECONDS = 3.0

# ``app.state`` attribute under which :func:`app.gateway.deps.langgraph_runtime`
# records the startup-bound checkpointer/Store config the probe targets.
READINESS_CHECKPOINTER_CONFIG_ATTR = "checkpointer_config"

# ``app.state`` attribute under which :func:`app.gateway.deps.langgraph_runtime`
# records the startup-bound provisioner base URL (``None`` when unset). The
# stream bridge needs no snapshot: the singleton itself lives on
# ``app.state.stream_bridge``.
READINESS_PROVISIONER_URL_ATTR = "readiness_provisioner_url"

# Probes whose ``unreachable`` verdict flips the endpoint to 503. The
# provisioner is deliberately absent: it is shared by every replica, so its
# verdict is informational and must never drain the whole service.
_GATING_PROBES = ("database", "checkpointer", "stream_bridge")

# One set of gates per running event loop (one per worker process in
# production; one per test loop in the suite). ``/health/ready`` is public and
# unauthenticated, so a thundering herd of probes - or an attacker - must never
# be able to open an unbounded number of new connections: every
# connection-opening probe below is serialized through the gate for its kind,
# bounding in-flight probe connections to one per kind per process. Gates are
# per kind rather than shared so the probes of one request still run
# concurrently and the endpoint deadline keeps holding for a healthy response.
# Waiting requests are still shed by the endpoint-wide deadline.
_PROBE_GATES: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = weakref.WeakKeyDictionary()


def _probe_gate(kind: str) -> asyncio.Lock:
    """Return the serialization gate for *kind* bound to the running loop."""
    loop = asyncio.get_running_loop()
    gates = _PROBE_GATES.get(loop)
    if gates is None:
        gates = {}
        _PROBE_GATES[loop] = gates
    gate = gates.get(kind)
    if gate is None:
        gate = asyncio.Lock()
        gates[kind] = gate
    return gate


# Result vocabulary shared by every probe.
PROBE_OK = "ok"
PROBE_NOT_CONFIGURED = "not_configured"
PROBE_UNREACHABLE = "unreachable"


async def check_database_health() -> str:
    """Probe the persistence engine; return one of the PROBE_* values."""
    engine = get_engine()
    if engine is None:
        # backend=memory, or the engine has not been initialized yet: there is
        # no database to probe.
        return PROBE_NOT_CONFIGURED
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Readiness database probe failed", exc_info=True)
        return PROBE_UNREACHABLE
    return PROBE_OK


def resolve_checkpointer_config(startup_config: AppConfig) -> CheckpointerConfig | None:
    """Resolve the checkpointer/Store backend bound to a startup config snapshot.

    Mirrors the runtime's own selection (the legacy ``checkpointer`` section
    first, otherwise derived from the unified ``database`` section), so the
    probe targets the exact backend ``langgraph_runtime`` built at startup -
    which can differ from the ORM ``database:`` backend and from a later,
    hot-reloaded config. Returns None when the config cannot be resolved;
    callers must treat that as a failure (unreachable), never as
    ``not_configured``.
    """
    from deerflow.runtime.checkpointer.provider import _resolve_checkpointer_config

    try:
        return _resolve_checkpointer_config(startup_config)
    except Exception:
        logger.warning(
            "Readiness probe: unable to resolve the startup checkpointer config; failing closed",
            exc_info=True,
        )
        return None


def _sqlite_disk_uri(conn_str: str) -> str:
    """Return a non-creating (``mode=rw``) SQLite URI for a disk-backed database.

    Opening with ``mode=rw`` refuses to create a missing database file, so a
    readiness probe can never resurrect a checkpointer/Store file that was
    deleted or lost after startup - absence must surface as unreachable. The
    path is already absolute after
    ``deerflow.runtime.store._sqlite_utils.resolve_sqlite_conn_str`` and is
    converted with ``Path.as_uri`` for correct percent-encoding.
    """
    return f"{pathlib.Path(conn_str).as_uri()}?mode=rw"


async def _probe_sqlite_backend(conn_string: str | None) -> str:
    """Probe a SQLite checkpointer/Store database with bounded open/query work.

    Disk-backed databases are opened non-creating (``mode=rw``): a missing
    file stays missing and fails the probe instead of being recreated empty.
    ``:memory:`` only exists inside the running process, so there is nothing
    external to probe and it reports ``not_configured`` like the memory
    backend. A connection string the runtime refuses (a SQLite ``file:`` URI)
    is unreachable.
    """
    try:
        import aiosqlite
    except ImportError:
        logger.error("Readiness probe: aiosqlite is not installed for the sqlite checkpointer backend")
        return PROBE_UNREACHABLE
    from deerflow.runtime.store._sqlite_utils import resolve_sqlite_conn_str

    try:
        conn_str = resolve_sqlite_conn_str(conn_string or "store.db")
    except ValueError as exc:
        logger.error("Readiness probe: %s", exc)
        return PROBE_UNREACHABLE
    if conn_str == ":memory:":
        return PROBE_NOT_CONFIGURED
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            connection = await aiosqlite.connect(_sqlite_disk_uri(conn_str), uri=True)
            try:
                await connection.execute("SELECT 1")
            finally:
                await await_drained(connection.close())
    except Exception:
        logger.warning("Readiness sqlite checkpointer probe failed", exc_info=True)
        return PROBE_UNREACHABLE
    return PROBE_OK


async def _probe_postgres_backend(conn_string: str, schema: str) -> str:
    """Probe PostgreSQL with bounded open/query work and drained connection teardown."""
    try:
        from psycopg import AsyncConnection
    except ImportError:
        logger.error("Readiness probe: psycopg is not installed for the postgres checkpointer backend")
        return PROBE_UNREACHABLE
    try:
        from deerflow.persistence.postgres_schema import dsn_with_search_path, normalize_libpq_dsn

        dsn = dsn_with_search_path(normalize_libpq_dsn(conn_string), schema)
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            connection = await AsyncConnection.connect(dsn, connect_timeout=int(_PROBE_TIMEOUT_SECONDS))
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            finally:
                await await_drained(connection.close())
    except Exception:
        logger.warning("Readiness postgres checkpointer probe failed", exc_info=True)
        return PROBE_UNREACHABLE
    return PROBE_OK


async def _probe_checkpointer_backend(config: CheckpointerConfig) -> str:
    """Probe the LangGraph checkpointer/Store backend described by *config*.

    *config* is the startup-bound snapshot (see :func:`resolve_checkpointer_config`);
    an in-process memory backend has nothing external to probe. Probes that
    open a connection (sqlite file, postgres) are serialized so concurrent
    unauthenticated requests cannot exhaust the database's connections.
    """
    if config.type == "memory":
        # In-process backend: there is nothing external to probe.
        return PROBE_NOT_CONFIGURED
    if config.type not in ("sqlite", "postgres"):
        logger.warning("Readiness probe: unknown checkpointer backend %r", config.type)
        return PROBE_UNREACHABLE
    async with _probe_gate("checkpointer"):
        if config.type == "sqlite":
            return await _probe_sqlite_backend(config.connection_string)
        if not config.connection_string:
            return PROBE_UNREACHABLE
        return await _probe_postgres_backend(config.connection_string, config.postgres_schema)


async def _probe_stream_bridge(bridge: StreamBridge | None) -> str:
    """Probe the stream bridge's external backend (Redis for the redis bridge).

    ``None`` fails closed: without a bridge no run can publish, stream or be
    cancelled across instances, so readiness must not be claimed. A
    process-local bridge (``supports_cross_process`` False) has nothing
    external to probe. Pings are serialized so unauthenticated probe traffic
    cannot grow the Redis connection pool; the bridge answers ``False`` for a
    backend-side failure and anything it raises counts the same way.
    """
    if bridge is None:
        logger.error("Readiness probe: no stream bridge recorded on app.state; failing closed")
        return PROBE_UNREACHABLE
    if not bridge.supports_cross_process:
        return PROBE_NOT_CONFIGURED
    async with _probe_gate("stream_bridge"):
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                reachable = await bridge.ping()
        except Exception:
            logger.warning("Readiness stream bridge probe failed", exc_info=True)
            return PROBE_UNREACHABLE
    if not reachable:
        logger.warning("Readiness stream bridge probe: backend reported unreachable")
        return PROBE_UNREACHABLE
    return PROBE_OK


def resolve_provisioner_url(startup_config: AppConfig) -> str | None:
    """Return the provisioner base URL from the startup snapshot, or ``None``.

    ``sandbox`` is a startup-only section (the provider singleton is built
    once), so the probe target is pinned at startup like the checkpointer
    snapshot. ``provisioner_url`` is an ``extra="allow"`` key on
    ``SandboxConfig`` that only ``AioSandboxProvider`` consumes, not a declared
    field, hence the ``getattr`` access. Blank values mean "no provisioner".
    """
    sandbox = getattr(startup_config, "sandbox", None)
    url = getattr(sandbox, "provisioner_url", None) if sandbox is not None else None
    if not isinstance(url, str):
        return None
    normalized = url.strip().rstrip("/")
    return normalized or None


def _make_provisioner_client(provisioner_url: str) -> httpx.AsyncClient:
    """Build the short-lived client for one provisioner probe (replaced in tests).

    Proxy handling mirrors the provisioner-bound sandbox clients: a loopback,
    private, link-local or cluster-local address (``provisioner``,
    ``*.docker.internal``) is control-plane traffic and bypasses ``HTTP_PROXY``,
    while an external host keeps the environment's proxy settings. Unlike the
    requests-based sandbox calls, httpx does not honour CIDR entries in
    ``NO_PROXY``, so without this a private provisioner behind a proxy-only
    egress would be reported unreachable on every probe.
    """
    # Lazy: importing the aio_sandbox package pulls in the whole provider stack.
    from deerflow.community.aio_sandbox.backend import sandbox_http_trust_env

    return httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS, trust_env=sandbox_http_trust_env(provisioner_url))


async def _probe_provisioner(provisioner_url: str | None) -> str:
    """Probe the sandbox provisioner's unauthenticated ``GET /health``.

    Report-only: :func:`readiness_payload` never degrades on this verdict,
    because every gateway replica shares one provisioner and a blip there
    must not drain the whole service. The probe is still serialized per
    process so public probe traffic cannot become a connection flood at the
    provisioner, and the per-probe budget bounds a hung connection.
    """
    if not provisioner_url:
        return PROBE_NOT_CONFIGURED
    async with _probe_gate("provisioner"):
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                async with _make_provisioner_client(provisioner_url) as client:
                    response = await client.get(f"{provisioner_url}/health")
        except Exception:
            logger.warning("Readiness provisioner probe failed", exc_info=True)
            return PROBE_UNREACHABLE
    if response.status_code != 200:
        logger.warning("Readiness provisioner probe: HTTP %s from %s/health", response.status_code, provisioner_url)
        return PROBE_UNREACHABLE
    return PROBE_OK


async def readiness_payload(
    checkpointer_config: CheckpointerConfig | None = None,
    *,
    stream_bridge: StreamBridge | None = None,
    provisioner_url: str | None = None,
) -> tuple[int, dict[str, str]]:
    """Return the (status_code, body) pair served by ``GET /health/ready``.

    Probes the backends the gateway depends on: the ORM engine behind
    ``database:`` (repositories), the effective LangGraph checkpointer/Store
    backend (the legacy ``checkpointer:`` section, otherwise derived from
    ``database:``) and the stream bridge's external backend, plus the
    report-only provisioner check. The probes run concurrently beneath one
    endpoint-wide deadline, so normal probe work is bounded by the slowest
    single probe rather than their sum; a probe that overruns the deadline is
    the only one marked unreachable, so a wedged report-only probe cannot
    flip the endpoint through the deadline path. Connection teardown is
    drained after cancellation to preserve ownership and can therefore extend
    the in-flight request beyond that deadline if close itself stalls.

    ``checkpointer_config`` and ``provisioner_url`` are the startup snapshots
    recorded by ``langgraph_runtime`` and ``stream_bridge`` is the singleton
    it built; a ``None`` checkpointer snapshot or bridge fails closed as
    unreachable rather than reporting ready, while a ``None`` provisioner URL
    simply means none is configured. Each gating backend can be configured
    independently of the others, so an unreachable verdict on any of them
    degrades the endpoint.
    """

    async def _probe_engine() -> str:
        return await check_database_health()

    async def _probe_checkpointer() -> str:
        if checkpointer_config is None:
            # Fail closed: without the startup-bound config we cannot know what
            # backend agent runs use, so readiness must not be claimed.
            logger.error("Readiness probe: no startup checkpointer config snapshot recorded; failing closed")
            return PROBE_UNREACHABLE
        return await _probe_checkpointer_backend(checkpointer_config)

    probes = {
        "database": _probe_engine(),
        "checkpointer": _probe_checkpointer(),
        "stream_bridge": _probe_stream_bridge(stream_bridge),
        "provisioner": _probe_provisioner(provisioner_url),
    }
    # Every verdict starts out unreachable and is overwritten as its probe
    # finishes, so a probe cancelled by the deadline fails alone instead of
    # erasing the answers the others already produced.
    results = dict.fromkeys(probes, PROBE_UNREACHABLE)
    pending = set(probes)

    async def _record(name: str, probe: Awaitable[str]) -> None:
        results[name] = await probe
        pending.discard(name)

    try:
        async with asyncio.timeout(_READINESS_DEADLINE_SECONDS):
            await asyncio.gather(*(_record(name, probe) for name, probe in probes.items()))
    except TimeoutError:
        logger.error(
            "Readiness probes exceeded the %.1fs endpoint deadline; failing %s",
            _READINESS_DEADLINE_SECONDS,
            ", ".join(sorted(pending)),
        )
    degraded = any(results[name] == PROBE_UNREACHABLE for name in _GATING_PROBES)
    payload = {
        "status": "degraded" if degraded else "ready",
        "service": "deer-flow-gateway",
        **results,
    }
    return (503 if degraded else 200, payload)
