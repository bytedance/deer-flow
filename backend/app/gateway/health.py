"""Readiness probe helpers for the gateway health endpoints.

``GET /health`` stays a pure liveness signal: 200 whenever the process is up.
``GET /health/ready`` additionally probes the persistence the gateway actually
depends on, so orchestrators (Docker healthchecks, Kubernetes probes) treat the
gateway as ready only when the databases behind agent runs are reachable. Two
backends can be configured independently:

* the ORM engine behind ``database:`` (application repositories), and
* the effective LangGraph checkpointer/Store backend - the legacy
  ``checkpointer:`` section when present, otherwise derived from ``database:``
  (memory/sqlite/postgres).

Both probes run concurrently beneath a single endpoint-wide deadline
(:data:`_READINESS_DEADLINE_SECONDS`), so a healthy response completes within
one probe window rather than the sum of both budgets. The checkpointer config
is resolved once at startup from the same snapshot ``langgraph_runtime`` builds
its resources from and is stored on ``app.state``; probing a hot-reloaded
config instead could check a backend the running process is not using. A
``backend=memory`` deployment has nothing to probe and is always considered
ready; a startup config that cannot be resolved fails closed as unreachable.
Connection-opening probes are serialized behind a strict per-process gate: the
route is public through the ``/health`` auth prefix, so unlimited concurrent
requests must never translate into unlimited new PostgreSQL connections.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import urllib.parse
import weakref
from typing import TYPE_CHECKING

from sqlalchemy import text

from deerflow.persistence.engine import get_engine

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.checkpointer_config import CheckpointerConfig

logger = logging.getLogger(__name__)

# Upper bound for a single probe attempt. The endpoint must never hang behind
# a dead database (for example a TCP connect timeout to Postgres).
_PROBE_TIMEOUT_SECONDS = 2.0

# Whole-endpoint deadline covering both probes. They run concurrently, so a
# healthy response completes within a single probe window; the extra margin
# absorbs scheduling/cancellation overhead without letting the request
# approach the sum of both probe budgets. Orchestrator timeouts (Helm
# readinessProbe ``timeoutSeconds``, the docker-compose healthcheck client
# timeout) must be configured above this bound.
_READINESS_DEADLINE_SECONDS = 3.0

# ``app.state`` attribute under which :func:`app.gateway.deps.langgraph_runtime`
# records the startup-bound checkpointer/Store config the probe targets.
READINESS_CHECKPOINTER_CONFIG_ATTR = "checkpointer_config"

# One gate per running event loop (one per worker process in production; one
# per test loop in the suite). ``/health/ready`` is public and unauthenticated,
# so a thundering herd of probes - or an attacker - must never be able to open
# an unbounded number of new connections: every connection-opening probe below
# is serialized through this gate, bounding in-flight probe connections to one
# per process. Waiting requests are still shed by the endpoint-wide deadline.
_PROBE_GATES: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = weakref.WeakKeyDictionary()


def _probe_gate() -> asyncio.Lock:
    """Return the serialization gate bound to the currently running loop."""
    loop = asyncio.get_running_loop()
    gate = _PROBE_GATES.get(loop)
    if gate is None:
        gate = asyncio.Lock()
        _PROBE_GATES[loop] = gate
    return gate


# Result vocabulary for the database probe.
DATABASE_OK = "ok"
DATABASE_NOT_CONFIGURED = "not_configured"
DATABASE_UNREACHABLE = "unreachable"


async def check_database_health() -> str:
    """Probe the persistence engine; return one of the DATABASE_* values."""
    engine = get_engine()
    if engine is None:
        # backend=memory, or the engine has not been initialized yet: there is
        # no database to probe.
        return DATABASE_NOT_CONFIGURED
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Readiness database probe failed", exc_info=True)
        return DATABASE_UNREACHABLE
    return DATABASE_OK


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


def _sqlite_is_in_memory(conn_str: str) -> bool:
    """Return True when *conn_str* refers to a purely in-memory SQLite database."""
    if conn_str == ":memory:":
        return True
    if not conn_str.startswith("file:"):
        return False
    parts = urllib.parse.urlsplit(conn_str)
    if parts.path in (":memory:", ""):
        return True
    return any(key == "mode" and value == "memory" for key, value in urllib.parse.parse_qsl(parts.query))


def _sqlite_disk_uri(conn_str: str) -> str:
    """Return a non-creating (``mode=rw``) SQLite URI for a disk-backed database.

    Opening with ``mode=rw`` refuses to create a missing database file, so a
    readiness probe can never resurrect a checkpointer/Store file that was
    deleted or lost after startup - absence must surface as unreachable. Plain
    filesystem paths (already absolute after
    ``deerflow.runtime.store._sqlite_utils.resolve_sqlite_conn_str``) are
    converted with ``Path.as_uri`` for correct percent-encoding; existing
    ``file:`` URIs keep their path bytes and get ``mode=rw`` merged into the
    query, replacing any pinned mode.
    """
    if not conn_str.startswith("file:"):
        return f"{pathlib.Path(conn_str).as_uri()}?mode=rw"
    parts = urllib.parse.urlsplit(conn_str)
    query_pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(key == "mode" for key, _ in query_pairs):
        separator = "&" if parts.query else "?"
        return f"{conn_str}{separator}mode=rw"
    replaced = urllib.parse.urlencode([(key, "rw") if key == "mode" else (key, value) for key, value in query_pairs])
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, replaced, parts.fragment))


async def _probe_sqlite_backend(conn_string: str | None) -> str:
    """Probe a SQLite checkpointer/Store database with a bounded SELECT 1.

    Disk-backed databases are opened non-creating (``mode=rw``): a missing
    file stays missing and fails the probe instead of being recreated empty.
    In-memory forms (``:memory:`` and ``file:`` URIs with ``mode=memory``)
    only exist inside the running process, so there is nothing external to
    probe and they report ``not_configured`` like the memory backend.
    """
    try:
        import aiosqlite
    except ImportError:
        logger.error("Readiness probe: aiosqlite is not installed for the sqlite checkpointer backend")
        return DATABASE_UNREACHABLE
    from deerflow.runtime.store._sqlite_utils import resolve_sqlite_conn_str

    conn_str = resolve_sqlite_conn_str(conn_string or "store.db")
    if _sqlite_is_in_memory(conn_str):
        return DATABASE_NOT_CONFIGURED
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            connection = await aiosqlite.connect(_sqlite_disk_uri(conn_str), uri=True)
            try:
                await connection.execute("SELECT 1")
            finally:
                await connection.close()
    except Exception:
        logger.warning("Readiness sqlite checkpointer probe failed", exc_info=True)
        return DATABASE_UNREACHABLE
    return DATABASE_OK


async def _probe_postgres_backend(conn_string: str, schema: str) -> str:
    """Probe a PostgreSQL checkpointer/Store database with a bounded SELECT 1."""
    try:
        from psycopg import AsyncConnection
    except ImportError:
        logger.error("Readiness probe: psycopg is not installed for the postgres checkpointer backend")
        return DATABASE_UNREACHABLE
    try:
        from deerflow.persistence.postgres_schema import dsn_with_search_path, normalize_libpq_dsn

        dsn = dsn_with_search_path(normalize_libpq_dsn(conn_string), schema)
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            connection = await AsyncConnection.connect(dsn, connect_timeout=int(_PROBE_TIMEOUT_SECONDS))
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            finally:
                await connection.close()
    except Exception:
        logger.warning("Readiness postgres checkpointer probe failed", exc_info=True)
        return DATABASE_UNREACHABLE
    return DATABASE_OK


async def _probe_checkpointer_backend(config: CheckpointerConfig) -> str:
    """Probe the LangGraph checkpointer/Store backend described by *config*.

    *config* is the startup-bound snapshot (see :func:`resolve_checkpointer_config`);
    an in-process memory backend has nothing external to probe. Probes that
    open a connection (sqlite file, postgres) are serialized so concurrent
    unauthenticated requests cannot exhaust the database's connections.
    """
    if config.type == "memory":
        # In-process backend: there is nothing external to probe.
        return DATABASE_NOT_CONFIGURED
    if config.type not in ("sqlite", "postgres"):
        logger.warning("Readiness probe: unknown checkpointer backend %r", config.type)
        return DATABASE_UNREACHABLE
    async with _probe_gate():
        if config.type == "sqlite":
            return await _probe_sqlite_backend(config.connection_string)
        if not config.connection_string:
            return DATABASE_UNREACHABLE
        return await _probe_postgres_backend(config.connection_string, config.postgres_schema)


async def readiness_payload(checkpointer_config: CheckpointerConfig | None = None) -> tuple[int, dict[str, str]]:
    """Return the (status_code, body) pair served by ``GET /health/ready``.

    Probes both persistence halves the gateway depends on: the ORM engine
    behind ``database:`` (repositories) and the effective LangGraph
    checkpointer/Store backend (the legacy ``checkpointer:`` section, otherwise
    derived from ``database:``). The probes run concurrently beneath one
    endpoint-wide deadline so the request duration is bounded by the slowest
    single probe, not their sum. ``checkpointer_config`` is the startup
    snapshot recorded by ``langgraph_runtime``; None means no snapshot could be
    resolved, which fails closed as an unreachable backend rather than
    reporting ready. Either backend can be configured independently of the
    other, so an unreachable probe on either degrades the endpoint.
    """

    async def _probe_engine() -> str:
        return await check_database_health()

    async def _probe_checkpointer() -> str:
        if checkpointer_config is None:
            # Fail closed: without the startup-bound config we cannot know what
            # backend agent runs use, so readiness must not be claimed.
            logger.error("Readiness probe: no startup checkpointer config snapshot recorded; failing closed")
            return DATABASE_UNREACHABLE
        return await _probe_checkpointer_backend(checkpointer_config)

    try:
        async with asyncio.timeout(_READINESS_DEADLINE_SECONDS):
            database, checkpointer = await asyncio.gather(_probe_engine(), _probe_checkpointer())
    except TimeoutError:
        logger.error(
            "Readiness probes exceeded the %.1fs endpoint deadline",
            _READINESS_DEADLINE_SECONDS,
        )
        database = checkpointer = DATABASE_UNREACHABLE
    degraded = DATABASE_UNREACHABLE in (database, checkpointer)
    payload = {
        "status": "degraded" if degraded else "ready",
        "service": "deer-flow-gateway",
        "database": database,
        "checkpointer": checkpointer,
    }
    return (503 if degraded else 200, payload)
