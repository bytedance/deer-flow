"""Async SQLAlchemy engine lifecycle management.

Initializes at Gateway startup, provides session factory for
repositories, disposes at shutdown.

When database.backend="memory", init_engine is a no-op and
get_session_factory() returns None. Repositories must check for
None and fall back to in-memory implementations.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Recycle pooled Postgres connections before stale idle sockets can hang
# pool_pre_ping. The command timeout bounds stalled ORM queries independently.
POSTGRES_POOL_RECYCLE_SECONDS = 300
POSTGRES_COMMAND_TIMEOUT_SECONDS = 30


def _json_serializer(obj: object) -> str:
    """JSON serializer with ensure_ascii=False for Chinese character support."""
    return json.dumps(obj, ensure_ascii=False)


def _postgres_engine_kwargs(
    *,
    echo: bool,
    pool_size: int,
    pool_recycle: int = POSTGRES_POOL_RECYCLE_SECONDS,
    command_timeout: float | None = POSTGRES_COMMAND_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Build the shared SQLAlchemy engine options for PostgreSQL."""
    connect_args = {}
    if command_timeout is not None:
        connect_args["command_timeout"] = command_timeout
    return {
        "echo": echo,
        "pool_size": pool_size,
        "pool_pre_ping": True,
        "pool_recycle": pool_recycle,
        "connect_args": connect_args,
        "json_serializer": _json_serializer,
    }


logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def _auto_create_postgres_db(url: str) -> None:
    """Connect to the ``postgres`` maintenance DB and CREATE DATABASE.

    The target database name is extracted from *url*.  The connection is
    made to the default ``postgres`` database on the same server using
    ``AUTOCOMMIT`` isolation (CREATE DATABASE cannot run inside a
    transaction).
    """
    from sqlalchemy import text
    from sqlalchemy.engine.url import make_url

    parsed = make_url(url)
    db_name = parsed.database
    if not db_name:
        raise ValueError("Cannot auto-create database: no database name in URL")

    # Connect to the default 'postgres' database to issue CREATE DATABASE
    maint_url = parsed.set(database="postgres")
    maint_engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    try:
        async with maint_engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        logger.info("Auto-created PostgreSQL database: %s", db_name)
    finally:
        await maint_engine.dispose()


async def init_engine(
    backend: str,
    *,
    url: str = "",
    echo: bool = False,
    pool_size: int = 5,
    pool_recycle: int = POSTGRES_POOL_RECYCLE_SECONDS,
    command_timeout: float | None = POSTGRES_COMMAND_TIMEOUT_SECONDS,
    sqlite_dir: str = "",
) -> None:
    """Create the async engine and session factory, then auto-create tables.

    Args:
        backend: "memory", "sqlite", or "postgres".
        url: SQLAlchemy async URL (for sqlite/postgres).
        echo: Echo SQL to log.
        pool_size: Postgres connection pool size.
        pool_recycle: Seconds before Postgres connections are recycled.
        command_timeout: Timeout in seconds for app ORM Postgres commands, or None to disable.
        sqlite_dir: Directory to create for SQLite (ensured to exist).
    """
    global _engine, _session_factory

    if backend == "memory":
        logger.info("Persistence backend=memory -- ORM engine not initialized")
        return

    if backend == "postgres":
        try:
            import asyncpg  # noqa: F401
        except ImportError:
            raise ImportError(
                "database.backend is set to 'postgres' but asyncpg is not installed.\n"
                "Install it with:\n"
                "    cd backend && uv sync --all-packages --extra postgres\n"
                "On the next `make dev` the postgres extra is auto-detected from\n"
                "config.yaml (database.backend: postgres) and reinstalled, so it\n"
                "will not be wiped again. Set UV_EXTRAS=postgres in .env to opt in\n"
                "explicitly. Or switch to backend: sqlite in config.yaml for\n"
                "single-node deployment."
            ) from None

    if backend == "sqlite":
        import os

        from sqlalchemy import event

        # Offload the directory creation: ``init_engine`` runs on the FastAPI
        # lifespan event loop, and a sync ``os.makedirs`` (a stat + mkdir
        # syscall) blocks it during startup. Mirrors the #1912 fix for the
        # checkpointer's ``ensure_sqlite_parent_dir``.
        await asyncio.to_thread(os.makedirs, sqlite_dir or ".", exist_ok=True)
        _engine = create_async_engine(url, echo=echo, json_serializer=_json_serializer)

        # Enable WAL on every new connection. SQLite PRAGMA settings are
        # per-connection, so we wire the listener instead of running PRAGMA
        # once at startup. WAL gives concurrent reads + writers without
        # blocking and is the standard recommendation for any production
        # SQLite deployment (TC-UPG-06 in AUTH_TEST_PLAN.md). The companion
        # ``synchronous=NORMAL`` is the safe-and-fast pairing — fsync only
        # at WAL checkpoint boundaries instead of every commit.
        # We also widen ``busy_timeout`` to 30s here. Python's sqlite3 driver
        # defaults to 5s, which is fine for transient row contention but too
        # tight for cross-process bootstrap: the second-N-th Gateway process
        # may need to wait while the first runs ``ALTER TABLE`` /
        # ``CREATE TABLE`` for a fresh schema. The same widened timeout is
        # mirrored on the alembic-spawned engine in
        # ``migrations/env.py::run_migrations_online`` so its connections
        # behave identically.
        @event.listens_for(_engine.sync_engine, "connect")
        def _enable_sqlite_wal(dbapi_conn, _record):  # noqa: ARG001 — SQLAlchemy contract
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.execute("PRAGMA busy_timeout=30000;")
            finally:
                cursor.close()
    elif backend == "postgres":
        _engine = create_async_engine(
            url,
            **_postgres_engine_kwargs(
                echo=echo,
                pool_size=pool_size,
                pool_recycle=pool_recycle,
                command_timeout=command_timeout,
            ),
        )
    else:
        raise ValueError(f"Unknown persistence backend: {backend!r}")

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # Schema bootstrap (hybrid):
    #   - empty DB        -> create_all + alembic stamp head
    #   - legacy DB       -> create_all (baseline tables only, backfill) + alembic stamp baseline + upgrade head
    #   - already managed -> alembic upgrade head
    # Concurrency: Postgres advisory lock (true cross-process); SQLite uses an
    # in-process asyncio.Lock plus a 30s PRAGMA busy_timeout (also set on
    # alembic's own connections in env.py) -- multi-process SQLite bootstrap
    # is best-effort, gated by SQLite's natural file-level write lock.
    # See deerflow.persistence.bootstrap for the full state machine.
    from deerflow.persistence.bootstrap import bootstrap_schema

    try:
        await bootstrap_schema(_engine, backend=backend)
    except Exception as exc:
        if backend == "postgres" and "does not exist" in str(exc):
            # Database not yet created -- attempt to auto-create it, then retry.
            await _auto_create_postgres_db(url)
            # Rebuild engine against the now-existing database
            await _engine.dispose()
            _engine = create_async_engine(
                url,
                **_postgres_engine_kwargs(
                    echo=echo,
                    pool_size=pool_size,
                    pool_recycle=pool_recycle,
                    command_timeout=command_timeout,
                ),
            )
            _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
            await bootstrap_schema(_engine, backend=backend)
        else:
            raise

    logger.info("Persistence engine initialized: backend=%s", backend)


async def init_engine_from_config(config) -> None:
    """Convenience: init engine from a DatabaseConfig object."""
    if config.backend == "memory":
        await init_engine("memory")
        return
    await init_engine(
        backend=config.backend,
        url=config.app_sqlalchemy_url,
        echo=config.echo_sql,
        pool_size=config.pool_size,
        pool_recycle=config.pool_recycle,
        command_timeout=config.command_timeout,
        sqlite_dir=config.sqlite_dir if config.backend == "sqlite" else "",
    )


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Return the async session factory, or None if backend=memory."""
    return _session_factory


def get_engine() -> AsyncEngine | None:
    """Return the async engine, or None if not initialized."""
    return _engine


async def close_engine() -> None:
    """Dispose the engine, release all connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Persistence engine closed")
    _engine = None
    _session_factory = None
