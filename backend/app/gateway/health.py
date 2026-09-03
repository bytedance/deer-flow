"""Readiness probe helpers for the gateway health endpoints.

``GET /health`` stays a pure liveness signal: 200 whenever the process is up.
``GET /health/ready`` additionally probes the persistence engine so
orchestrators (Docker healthchecks, Kubernetes probes) can treat the gateway
as ready only when the database is actually reachable. A ``backend=memory``
deployment has no engine to probe and is always considered ready.
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


async def readiness_payload() -> tuple[int, dict[str, str]]:
    """Return the (status_code, body) pair served by ``GET /health/ready``."""
    database = await check_database_health()
    if database == DATABASE_UNREACHABLE:
        return 503, {"status": "degraded", "service": "deer-flow-gateway", "database": database}
    return 200, {"status": "ready", "service": "deer-flow-gateway", "database": database}
