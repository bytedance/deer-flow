"""Sync Store factory.

Provides a **sync singleton** and a **sync context manager** for CLI tools
and the embedded :class:`~deerflow.client.DeerFlowClient`.

The store follows the legacy ``checkpointer`` section when present;
otherwise it mirrors the unified ``database`` section. Supported backends:
memory, sqlite, postgres.

Usage::

    from deerflow.runtime.store.provider import get_store, store_context

    # Singleton — reused across calls, closed on process exit
    store = get_store()

    # One-shot — fresh connection, closed on block exit
    with store_context() as store:
        store.put(("ns",), "key", {"value": 1})
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator

from langgraph.store.base import BaseStore

from deerflow.config.app_config import get_app_config
from deerflow.config.checkpointer_config import ensure_config_loaded
from deerflow.persistence.postgres_schema import create_schema_sql, dsn_with_search_path
from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir, resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error message constants
# ---------------------------------------------------------------------------

SQLITE_STORE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite store. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_STORE_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL store. Install the package extra with: pip install 'deerflow-harness[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"


def _ensure_postgres_schema(conn_string: str, schema: str) -> None:
    """Create the configured schema before LangGraph creates its store tables."""
    statement = create_schema_sql(schema)
    if statement is None:
        return
    import psycopg

    with psycopg.connect(conn_string, autocommit=True) as conn:
        conn.execute(statement)

# ---------------------------------------------------------------------------
# Sync factory
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _sync_store_cm(config) -> Iterator[BaseStore]:
    """Context manager that creates and tears down a sync Store.

    The ``config`` argument is a
    :class:`~deerflow.config.checkpointer_config.CheckpointerConfig` instance —
    the same object used by the checkpointer factory.
    """
    if config.type == "memory":
        from langgraph.store.memory import InMemoryStore

        logger.info("Store: using InMemoryStore (in-process, not persistent)")
        yield InMemoryStore()
        return

    if config.type == "sqlite":
        try:
            from langgraph.store.sqlite import SqliteStore
        except ImportError as exc:
            raise ImportError(SQLITE_STORE_INSTALL) from exc

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
        ensure_sqlite_parent_dir(conn_str)

        with SqliteStore.from_conn_string(conn_str) as store:
            store.setup()
            logger.info("Store: using SqliteStore (%s)", conn_str)
            yield store
        return

    if config.type == "postgres":
        try:
            from langgraph.store.postgres import PostgresStore  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(POSTGRES_STORE_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        _ensure_postgres_schema(config.connection_string, config.postgres_schema)
        conn_string = dsn_with_search_path(config.connection_string, config.postgres_schema)
        with PostgresStore.from_conn_string(conn_string) as store:
            store.setup()
            logger.info("Store: using PostgresStore")
            yield store
        return

    raise ValueError(f"Unknown store backend type: {config.type!r}")


@contextlib.contextmanager
def _sync_store_from_database(db_config) -> Iterator[BaseStore]:
    """Context manager that constructs a Store from unified DatabaseConfig."""
    if db_config.backend == "memory":
        from langgraph.store.memory import InMemoryStore

        yield InMemoryStore()
        return

    if db_config.backend == "sqlite":
        try:
            from langgraph.store.sqlite import SqliteStore
        except ImportError as exc:
            raise ImportError(SQLITE_STORE_INSTALL) from exc

        conn_str = db_config.checkpointer_sqlite_path
        ensure_sqlite_parent_dir(conn_str)
        with SqliteStore.from_conn_string(conn_str) as store:
            store.setup()
            logger.info("Store: using SqliteStore (%s)", conn_str)
            yield store
        return

    if db_config.backend == "postgres":
        try:
            from langgraph.store.postgres import PostgresStore  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(POSTGRES_STORE_INSTALL) from exc

        if not db_config.postgres_url:
            raise ValueError("database.postgres_url is required for the postgres backend")

        _ensure_postgres_schema(db_config.postgres_url, db_config.postgres_schema)
        conn_string = dsn_with_search_path(db_config.postgres_url, db_config.postgres_schema)
        with PostgresStore.from_conn_string(conn_string) as store:
            store.setup()
            logger.info("Store: using PostgresStore")
            yield store
        return

    raise ValueError(f"Unknown database backend: {db_config.backend!r}")


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_store: BaseStore | None = None
_store_ctx = None  # open context manager keeping the connection alive
_store_lock = threading.Lock()


def get_store() -> BaseStore:
    """Return the global sync Store singleton, creating it on first call.

    Returns an :class:`~langgraph.store.memory.InMemoryStore` when no
    checkpointer is configured in *config.yaml* (emits a WARNING in that case).

    Raises:
        ImportError: If the required package for the configured backend is not installed.
        ValueError: If ``connection_string`` is missing for a backend that requires it.
    """
    global _store, _store_ctx

    if _store is not None:
        return _store

    # Config loading can reset both persistence singletons. Keep it outside
    # this provider lock to avoid cross-provider lock-order inversion.
    ensure_config_loaded()

    with _store_lock:
        if _store is not None:
            return _store

        from deerflow.config.checkpointer_config import get_checkpointer_config

        config = get_checkpointer_config()

        if config is None:
            try:
                app_config = get_app_config()
            except FileNotFoundError:
                app_config = None
            db_config = getattr(app_config, "database", None) if app_config is not None else None
            if db_config is not None and db_config.backend != "memory":
                store_ctx = _sync_store_from_database(db_config)
                store = store_ctx.__enter__()
                _store_ctx = store_ctx
                _store = store
                return _store

            from langgraph.store.memory import InMemoryStore

            logger.warning("No 'checkpointer' section in config.yaml — using InMemoryStore for the store. Thread list will be lost on server restart. Configure a sqlite or postgres backend for persistence.")
            _store = InMemoryStore()
            return _store

        store_ctx = _sync_store_cm(config)
        store = store_ctx.__enter__()
        _store_ctx = store_ctx
        _store = store
    return _store


def reset_store() -> None:
    """Reset the sync singleton, forcing recreation on the next call.

    Closes any open backend connections and clears the cached instance.
    Useful in tests or after a configuration change.
    """
    global _store, _store_ctx
    with _store_lock:
        if _store_ctx is not None:
            try:
                _store_ctx.__exit__(None, None, None)
            except Exception:
                logger.warning("Error during store cleanup", exc_info=True)
            _store_ctx = None
        _store = None


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def store_context() -> Iterator[BaseStore]:
    """Sync context manager that yields a Store and cleans up on exit.

    Unlike :func:`get_store`, this does **not** cache the instance — each
    ``with`` block creates and destroys its own connection.  Use it in CLI
    scripts or tests where you want deterministic cleanup::

        with store_context() as store:
            store.put(("threads",), thread_id, {...})

    Yields an :class:`~langgraph.store.memory.InMemoryStore` when no
    checkpointer is configured in *config.yaml*.
    """
    config = get_app_config()
    if config.checkpointer is not None:
        with _sync_store_cm(config.checkpointer) as store:
            yield store
            return

    db_config = getattr(config, "database", None)
    if db_config is not None and db_config.backend != "memory":
        with _sync_store_from_database(db_config) as store:
            yield store
            return

    from langgraph.store.memory import InMemoryStore

    logger.warning("No 'checkpointer' section in config.yaml — using InMemoryStore for the store. Thread list will be lost on server restart. Configure a sqlite or postgres backend for persistence.")
    yield InMemoryStore()
