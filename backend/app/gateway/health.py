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

A ``backend=memory`` deployment has nothing to probe and is always considered
ready.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from deerflow.persistence.engine import get_engine

logger = logging.getLogger(__name__)

# Upper bound for a single probe attempt. The endpoint must never hang behind
# a dead database (for example a TCP connect timeout to Postgres).
_DB_PROBE_TIMEOUT_SECONDS = 2.0

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
        async with asyncio.timeout(_DB_PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Readiness database probe failed", exc_info=True)
        return DATABASE_UNREACHABLE
    return DATABASE_OK


def _effective_checkpointer_config():
    """Return the CheckpointerConfig agent runs actually checkpoint to, or None.

    Reuses the runtime's own resolution (the legacy ``checkpointer`` config
    singleton first, otherwise derived from the unified ``database`` section),
    so the probe targets the same backend the LangGraph checkpointer and Store
    use - which can differ from the ORM ``database:`` backend.
    """
    from deerflow.runtime.checkpointer.provider import _get_checkpointer_config

    try:
        return _get_checkpointer_config()
    except Exception:
        logger.warning("Readiness probe: unable to resolve the effective checkpointer config", exc_info=True)
        return None


async def _probe_sqlite_backend(conn_string: str | None) -> str:
    """Probe a SQLite checkpointer/Store database with a bounded SELECT 1."""
    try:
        import aiosqlite
    except ImportError:
        logger.error("Readiness probe: aiosqlite is not installed for the sqlite checkpointer backend")
        return DATABASE_UNREACHABLE
    from deerflow.runtime.store._sqlite_utils import resolve_sqlite_conn_str

    conn_str = resolve_sqlite_conn_str(conn_string or "store.db")
    try:
        async with asyncio.timeout(_DB_PROBE_TIMEOUT_SECONDS):
            connection = await aiosqlite.connect(conn_str, uri=conn_str.startswith("file:"))
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
        async with asyncio.timeout(_DB_PROBE_TIMEOUT_SECONDS):
            connection = await AsyncConnection.connect(dsn, connect_timeout=int(_DB_PROBE_TIMEOUT_SECONDS))
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            finally:
                await connection.close()
    except Exception:
        logger.warning("Readiness postgres checkpointer probe failed", exc_info=True)
        return DATABASE_UNREACHABLE
    return DATABASE_OK


async def _probe_checkpointer_backend() -> str:
    """Probe the effective LangGraph checkpointer/Store backend."""
    config = _effective_checkpointer_config()
    if config is None:
        return DATABASE_NOT_CONFIGURED
    if config.type == "memory":
        # In-process backend: there is nothing external to probe.
        return DATABASE_NOT_CONFIGURED
    if config.type == "sqlite":
        return await _probe_sqlite_backend(config.connection_string)
    if config.type == "postgres":
        if not config.connection_string:
            return DATABASE_UNREACHABLE
        return await _probe_postgres_backend(config.connection_string, config.postgres_schema)
    logger.warning("Readiness probe: unknown checkpointer backend %r", config.type)
    return DATABASE_UNREACHABLE


async def readiness_payload() -> tuple[int, dict[str, str]]:
    """Return the (status_code, body) pair served by ``GET /health/ready``.

    Probes both persistence halves the gateway depends on: the ORM engine
    behind ``database:`` (repositories) and the effective LangGraph
    checkpointer/Store backend (the legacy ``checkpointer:`` section, otherwise
    derived from ``database:``). Either backend can be configured independently
    of the other, so an unreachable probe on either degrades the endpoint.
    """
    database = await check_database_health()
    checkpointer = await _probe_checkpointer_backend()
    degraded = DATABASE_UNREACHABLE in (database, checkpointer)
    payload = {
        "status": "degraded" if degraded else "ready",
        "service": "deer-flow-gateway",
        "database": database,
        "checkpointer": checkpointer,
    }
    return (503 if degraded else 200, payload)
