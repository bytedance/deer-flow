"""Async Store factory — backend mirrors configured persistence.

The store follows the same persistence priority as the checkpointer:
legacy ``checkpointer`` configuration first, then the unified ``database``
configuration, and finally in-memory fallback.

- ``type: memory``   → :class:`langgraph.store.memory.InMemoryStore`
- ``type: sqlite``   → :class:`langgraph.store.sqlite.aio.AsyncSqliteStore`
- ``type: postgres`` → :class:`langgraph.store.postgres.aio.AsyncPostgresStore`

Usage (e.g. FastAPI lifespan)::

    from deerflow.runtime.store import make_store

    async with make_store() as store:
        app.state.store = store
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.store.base import BaseStore

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.runtime.store.provider import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_DATABASE_URL_REQUIRED,
    POSTGRES_STORE_INSTALL,
    SQLITE_STORE_INSTALL,
    ensure_sqlite_parent_dir,
    resolve_sqlite_conn_str,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal backend factory
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_store(config) -> AsyncIterator[BaseStore]:
    """Async context manager that constructs and tears down a Store.

    The ``config`` argument is a :class:`deerflow.config.checkpointer_config.CheckpointerConfig`
    instance — the same object used by the checkpointer factory.
    """
    if config.type == "memory":
        from langgraph.store.memory import InMemoryStore

        logger.info("Store: using InMemoryStore (in-process, not persistent)")
        yield InMemoryStore()
        return

    if config.type == "sqlite":
        try:
            from langgraph.store.sqlite.aio import AsyncSqliteStore
        except ImportError as exc:
            raise ImportError(SQLITE_STORE_INSTALL) from exc

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
        ensure_sqlite_parent_dir(conn_str)

        async with AsyncSqliteStore.from_conn_string(conn_str) as store:
            await store.setup()
            logger.info("Store: using AsyncSqliteStore (%s)", conn_str)
            yield store
        return

    if config.type == "postgres":
        try:
            from langgraph.store.postgres.aio import AsyncPostgresStore  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(POSTGRES_STORE_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        async with AsyncPostgresStore.from_conn_string(config.connection_string) as store:
            await store.setup()
            logger.info("Store: using AsyncPostgresStore")
            yield store
        return

    raise ValueError(f"Unknown store backend type: {config.type!r}")


@contextlib.asynccontextmanager
async def _async_store_from_database(db_config) -> AsyncIterator[BaseStore]:
    """Construct a Store from the unified DatabaseConfig."""
    if db_config.backend == "memory":
        from langgraph.store.memory import InMemoryStore

        logger.info("Store: using InMemoryStore (in-process, not persistent)")
        yield InMemoryStore()
        return

    if db_config.backend == "sqlite":
        try:
            from langgraph.store.sqlite.aio import AsyncSqliteStore
        except ImportError as exc:
            raise ImportError(SQLITE_STORE_INSTALL) from exc

        conn_str = db_config.sqlite_path
        ensure_sqlite_parent_dir(conn_str)

        async with AsyncSqliteStore.from_conn_string(conn_str) as store:
            await store.setup()
            logger.info("Store: using AsyncSqliteStore (%s)", conn_str)
            yield store
        return

    if db_config.backend == "postgres":
        try:
            from langgraph.store.postgres.aio import AsyncPostgresStore  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(POSTGRES_STORE_INSTALL) from exc

        if not db_config.postgres_url:
            raise ValueError(POSTGRES_DATABASE_URL_REQUIRED)

        async with AsyncPostgresStore.from_conn_string(db_config.postgres_url) as store:
            await store.setup()
            logger.info("Store: using AsyncPostgresStore")
            yield store
        return

    raise ValueError(f"Unknown database backend: {db_config.backend!r}")


# ---------------------------------------------------------------------------
# Public async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def make_store(app_config: AppConfig | None = None) -> AsyncIterator[BaseStore]:
    """Async context manager that yields a Store whose backend matches configured persistence.

    Uses the same priority as
    :func:`deerflow.runtime.checkpointer.async_provider.make_checkpointer`::

        async with make_store(app_config) as store:
            app.state.store = store

    Yields an :class:`~langgraph.store.memory.InMemoryStore` when no
    persistent backend is configured.
    """
    if app_config is None:
        app_config = get_app_config()

    if app_config.checkpointer is not None:
        async with _async_store(app_config.checkpointer) as store:
            yield store
            return

    db_config = getattr(app_config, "database", None)
    if db_config is not None and db_config.backend != "memory":
        async with _async_store_from_database(db_config) as store:
            yield store
            return

    from langgraph.store.memory import InMemoryStore

    logger.warning("No persistent store backend configured — using InMemoryStore for the store. Thread list will be lost on server restart. Configure a sqlite or postgres backend for persistence.")
    yield InMemoryStore()
    return
