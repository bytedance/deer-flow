"""Enterprise SQLAlchemy engine wrapper.

Manages the lifecycle of a separate async SQLAlchemy engine dedicated to
enterprise tables (RBAC, audit, approval, OIDC links). Schema management
is delegated to Alembic — the runtime ``init()`` only confirms the
connection works (``SELECT 1``); it never calls ``Base.metadata.create_all``.

Operators run ``alembic upgrade head`` against the enterprise database
URL during deploy; see RFC §8.1 / §8.4.

SQLite tuning
=============

The audit hot path (``AuditMiddleware.append``) commits one row per
tool call. Default SQLite (``journal_mode=DELETE``, ``synchronous=FULL``)
fsyncs the rollback journal twice per commit, giving 10-50ms P99 on
Windows. Switching to WAL + ``synchronous=NORMAL`` keeps durability
across crashes but lets the OS batch fsyncs, taking the same workload
from ~83ms P99 to ~6ms P99 (see ``tests/enterprise/bench_audit_append.py``).
We apply these pragmas in ``init()`` for SQLite URLs only — Postgres
ignores them.
"""

from __future__ import annotations

import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from deerflow.enterprise.config import EnterpriseDatabaseConfig

logger = logging.getLogger(__name__)


def _enable_sqlite_wal(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    """Apply WAL pragmas on every fresh SQLite connection.

    SQLAlchemy's ``connect`` event fires once per DBAPI connection — for
    SQLite + aiosqlite with NullPool that means once per session, which
    is exactly what we want: every connection enters the pool already
    tuned, so the audit append hot path never hits a slow connection.

    Pragmas chosen:
      - ``journal_mode=WAL``: write-ahead log keeps readers and writers
        out of each other's way.
      - ``synchronous=NORMAL``: skip the rollback-journal fsync; durable
        across application crashes, only loses an uncommitted write on
        OS crash. Acceptable for audit (we replay missing rows from app
        logs if needed).
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


class EnterpriseDatabase:
    """Async SQLAlchemy engine wrapper for enterprise tables.

    Construction does not open any connection — ``init()`` does. Callers
    should treat ``init()`` / ``close()`` as idempotent lifecycle hooks
    invoked from FastAPI's ``lifespan`` (M1+ wires this up).
    """

    def __init__(self, config: EnterpriseDatabaseConfig) -> None:
        self._config = config
        engine_kwargs: dict[str, object] = {"echo": config.echo}
        # SQLAlchemy raises if pool_size is passed to a SQLite (NullPool/StaticPool)
        # engine; only forward it for backends that actually pool.
        if not config.url.startswith(("sqlite", "sqlite+aiosqlite")):
            engine_kwargs["pool_size"] = config.pool_size
            engine_kwargs["pool_pre_ping"] = True
        self.engine: AsyncEngine = create_async_engine(config.url, **engine_kwargs)
        # For SQLite, re-apply WAL pragmas on every new connection. The
        # ``sync_engine`` is the SQLAlchemy core engine the async wrapper
        # delegates to; ``event.listens_for`` only accepts sync events.
        if config.url.startswith(("sqlite", "sqlite+aiosqlite")):
            event.listens_for(self.engine.sync_engine, "connect")(_enable_sqlite_wal)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        """Initialize the connection pool with a liveness probe.

        Schema creation is intentionally NOT performed here. ``alembic
        upgrade head`` is the single source of truth for schema state
        (RFC §8.1). Auto-creating tables on startup would mask migration
        gaps and conflict with audit / compliance expectations.
        """
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("EnterpriseDatabase initialised: url=%s", self._config.url)

    async def close(self) -> None:
        """Dispose the engine and release pooled connections."""
        await self.engine.dispose()
        logger.info("EnterpriseDatabase closed")


# ── process-wide singleton accessor ───────────────────────────────────
#
# The gateway lifespan constructs an :class:`EnterpriseDatabase` once at
# startup and registers it here via :func:`set_enterprise_database`.
# Downstream call sites — RBAC repo, audit storage, approval engine —
# call :func:`get_enterprise_database` instead of plumbing the instance
# through every constructor. This mirrors the pattern that
# ``app.gateway.authz`` uses for the permission provider.


_enterprise_database: EnterpriseDatabase | None = None


def set_enterprise_database(db: EnterpriseDatabase | None) -> None:
    """Register (or clear) the process-wide enterprise database."""
    global _enterprise_database
    _enterprise_database = db


def get_enterprise_database() -> EnterpriseDatabase:
    """Return the registered :class:`EnterpriseDatabase`.

    Raises ``RuntimeError`` if no instance has been registered yet —
    accessing the database before the gateway lifespan has wired it up
    is always a bug, never a race we want to silently paper over.
    """
    if _enterprise_database is None:
        raise RuntimeError(
            "Enterprise database not initialised — set_enterprise_database() "
            "must be called from the gateway lifespan before enterprise modules "
            "open sessions.",
        )
    return _enterprise_database


def get_enterprise_session_factory() -> async_sessionmaker[AsyncSession]:
    """Convenience: return the session factory from the registered DB."""
    return get_enterprise_database().session_factory


__all__ = [
    "EnterpriseDatabase",
    "get_enterprise_database",
    "get_enterprise_session_factory",
    "set_enterprise_database",
]
