"""Sync Store factory.

Provides a **sync singleton** and a **sync context manager** for CLI tools
and the embedded :class:`~deerflow.client.DeerFlowClient`.

The backend mirrors the configured checkpointer so that both always use the
same persistence technology.  Supported backends: memory, sqlite, postgres.

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
from collections.abc import Iterator

from langgraph.store.base import BaseStore

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir, resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error message constants
# ---------------------------------------------------------------------------

SQLITE_STORE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite store. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_STORE_INSTALL = "langgraph-checkpoint-postgres is required for the PostgreSQL store. Install it with: uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool"
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"

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

        with PostgresStore.from_conn_string(config.connection_string) as store:
            store.setup()
            logger.info("Store: using PostgresStore")
            yield store
        return

    raise ValueError(f"Unknown store backend type: {config.type!r}")


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_store: BaseStore | None = None
_store_ctx = None  # open context manager keeping the connection alive
_explicit_stores: dict[int, BaseStore] = {}
_explicit_store_contexts: dict[int, object] = {}


def _default_in_memory_store() -> BaseStore:
    from langgraph.store.memory import InMemoryStore

    logger.warning("No 'checkpointer' section in config.yaml — using InMemoryStore for the store. Thread list will be lost on server restart. Configure a sqlite or postgres backend for persistence.")
    return InMemoryStore()


def _build_store_from_app_config(app_config: AppConfig) -> tuple[BaseStore, object | None]:
    if app_config.checkpointer is not None:
        ctx = _sync_store_cm(app_config.checkpointer)
        return ctx.__enter__(), ctx

    return _default_in_memory_store(), None


def get_store(app_config: AppConfig | None = None) -> BaseStore:
    """Return the global sync Store singleton, creating it on first call.

    Returns an :class:`~langgraph.store.memory.InMemoryStore` when no
    checkpointer is configured in *config.yaml* (emits a WARNING in that case).

    Raises:
        ImportError: If the required package for the configured backend is not installed.
        ValueError: If ``connection_string`` is missing for a backend that requires it.
    """
    global _store, _store_ctx

    if app_config is not None:
        cache_key = id(app_config)
        cached = _explicit_stores.get(cache_key)
        if cached is not None:
            return cached

        explicit_store, explicit_ctx = _build_store_from_app_config(app_config)
        _explicit_stores[cache_key] = explicit_store
        if explicit_ctx is not None:
            _explicit_store_contexts[cache_key] = explicit_ctx
        return explicit_store

    if _store is not None:
        return _store

    # Lazily load app config, mirroring the checkpointer singleton pattern so
    # that tests that set the global checkpointer config explicitly remain isolated.
    from deerflow.config.app_config import _app_config
    from deerflow.config.checkpointer_config import get_checkpointer_config

    config = get_checkpointer_config()

    if config is None and _app_config is None:
        try:
            get_app_config()
        except FileNotFoundError:
            pass
        config = get_checkpointer_config()

    if config is None:
        _store = _default_in_memory_store()
        return _store

    _store_ctx = _sync_store_cm(config)
    _store = _store_ctx.__enter__()
    return _store


def reset_store() -> None:
    """Reset the sync singleton, forcing recreation on the next call.

    Closes any open backend connections and clears the cached instance.
    Useful in tests or after a configuration change.
    """
    global _store, _store_ctx
    if _store_ctx is not None:
        try:
            _store_ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during store cleanup", exc_info=True)
        _store_ctx = None
    _store = None

    for cache_key, ctx in list(_explicit_store_contexts.items()):
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during explicit store cleanup", exc_info=True)
        finally:
            _explicit_store_contexts.pop(cache_key, None)
            _explicit_stores.pop(cache_key, None)

    _explicit_stores.clear()
    _explicit_store_contexts.clear()


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def store_context(app_config: AppConfig | None = None) -> Iterator[BaseStore]:
    """Sync context manager that yields a Store and cleans up on exit.

    Unlike :func:`get_store`, this does **not** cache the instance — each
    ``with`` block creates and destroys its own connection.  Use it in CLI
    scripts or tests where you want deterministic cleanup::

        with store_context() as store:
            store.put(("threads",), thread_id, {...})

    Yields an :class:`~langgraph.store.memory.InMemoryStore` when no
    checkpointer is configured in *config.yaml*.
    """
    resolved_app_config = app_config or get_app_config()
    if resolved_app_config.checkpointer is None:
        yield _default_in_memory_store()
        return

    with _sync_store_cm(resolved_app_config.checkpointer) as store:
        yield store
