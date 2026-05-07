"""Sync checkpointer factory.

Provides a **sync singleton** and a **sync context manager** for LangGraph
graph compilation and CLI tools.

Supported backends: memory, sqlite, postgres.

Usage::

    from deerflow.runtime.checkpointer.provider import get_checkpointer, checkpointer_context

    # Singleton — reused across calls, closed on process exit
    cp = get_checkpointer()

    # One-shot — fresh connection, closed on block exit
    with checkpointer_context() as cp:
        graph.invoke(input, config={"configurable": {"thread_id": "1"}})
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig
from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir, resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error message constants — imported by aio.provider too
# ---------------------------------------------------------------------------

SQLITE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite checkpointer. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_INSTALL = "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install it with: uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool"
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"

# ---------------------------------------------------------------------------
# Sync factory
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _sync_checkpointer_cm(config: CheckpointerConfig) -> Iterator[Checkpointer]:
    """Context manager that creates and tears down a sync checkpointer.

    Returns a configured ``Checkpointer`` instance. Resource cleanup for any
    underlying connections or pools is handled by higher-level helpers in
    this module (such as the singleton factory or context manager); this
    function does not return a separate cleanup callback.
    """
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
        yield InMemorySaver()
        return

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
        ensure_sqlite_parent_dir(conn_str)
        with SqliteSaver.from_conn_string(conn_str) as saver:
            saver.setup()
            logger.info("Checkpointer: using SqliteSaver (%s)", conn_str)
            yield saver
        return

    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        with PostgresSaver.from_conn_string(config.connection_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_checkpointer: Checkpointer | None = None
_checkpointer_ctx = None  # open context manager keeping the connection alive
_explicit_checkpointers: dict[int, Checkpointer] = {}
_explicit_checkpointer_contexts: dict[int, object] = {}


def _default_in_memory_checkpointer() -> Checkpointer:
    from langgraph.checkpoint.memory import InMemorySaver

    logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
    return InMemorySaver()


def _persistent_database_backend(db_config) -> str | None:
    backend = getattr(db_config, "backend", None)
    if backend in {"sqlite", "postgres"}:
        return backend
    return None


@contextlib.contextmanager
def _sync_checkpointer_from_database_cm(db_config) -> Iterator[Checkpointer]:
    """Context manager that creates a sync checkpointer from unified DatabaseConfig."""
    backend = _persistent_database_backend(db_config)
    if backend is None:
        yield _default_in_memory_checkpointer()
        return

    if backend == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = db_config.checkpointer_sqlite_path
        ensure_sqlite_parent_dir(conn_str)
        with SqliteSaver.from_conn_string(conn_str) as saver:
            saver.setup()
            logger.info("Checkpointer: using SqliteSaver (%s)", conn_str)
            yield saver
        return

    if backend == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not db_config.postgres_url:
            raise ValueError("database.postgres_url is required for the postgres backend")

        with PostgresSaver.from_conn_string(db_config.postgres_url) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown database backend: {backend!r}")


def _build_checkpointer_from_app_config(app_config: AppConfig) -> tuple[Checkpointer, object | None]:
    if app_config.checkpointer is not None:
        ctx = _sync_checkpointer_cm(app_config.checkpointer)
        return ctx.__enter__(), ctx

    db_config = getattr(app_config, "database", None)
    if _persistent_database_backend(db_config) is not None:
        ctx = _sync_checkpointer_from_database_cm(db_config)
        return ctx.__enter__(), ctx

    return _default_in_memory_checkpointer(), None


def get_checkpointer(app_config: AppConfig | None = None) -> Checkpointer:
    """Return the global sync checkpointer singleton, creating it on first call.

    Returns an ``InMemorySaver`` when no checkpointer is configured in *config.yaml*.

    Raises:
        ImportError: If the required package for the configured backend is not installed.
        ValueError: If ``connection_string`` is missing for a backend that requires it.
    """
    global _checkpointer, _checkpointer_ctx

    if app_config is not None:
        cache_key = id(app_config)
        cached = _explicit_checkpointers.get(cache_key)
        if cached is not None:
            return cached

        explicit_checkpointer, explicit_ctx = _build_checkpointer_from_app_config(app_config)
        _explicit_checkpointers[cache_key] = explicit_checkpointer
        if explicit_ctx is not None:
            _explicit_checkpointer_contexts[cache_key] = explicit_ctx
        return explicit_checkpointer

    if _checkpointer is not None:
        return _checkpointer

    # Ensure app config is loaded before checking checkpointer config
    # This prevents returning InMemorySaver when config.yaml actually has a checkpointer section
    # but hasn't been loaded yet
    from deerflow.config.app_config import _app_config
    from deerflow.config.checkpointer_config import get_checkpointer_config

    config = get_checkpointer_config()
    global_app_config = _app_config

    if config is None and global_app_config is None:
        # Only load app config lazily when neither the app config nor an explicit
        # checkpointer config has been initialized yet. This keeps tests that
        # intentionally set the global checkpointer config isolated from any
        # ambient config.yaml on disk.
        try:
            global_app_config = get_app_config()
        except FileNotFoundError:
            # In test environments without config.yaml, this is expected.
            pass
        config = get_checkpointer_config()

    if config is not None:
        _checkpointer_ctx = _sync_checkpointer_cm(config)
        _checkpointer = _checkpointer_ctx.__enter__()
        return _checkpointer

    if global_app_config is not None:
        _checkpointer, _checkpointer_ctx = _build_checkpointer_from_app_config(global_app_config)
        return _checkpointer

    _checkpointer = _default_in_memory_checkpointer()
    return _checkpointer


def reset_checkpointer() -> None:
    """Reset the sync singleton, forcing recreation on the next call.

    Closes any open backend connections and clears the cached instance.
    Useful in tests or after a configuration change.
    """
    global _checkpointer, _checkpointer_ctx
    if _checkpointer_ctx is not None:
        try:
            _checkpointer_ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during checkpointer cleanup", exc_info=True)
        _checkpointer_ctx = None
    _checkpointer = None

    for cache_key, ctx in list(_explicit_checkpointer_contexts.items()):
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during explicit checkpointer cleanup", exc_info=True)
        finally:
            _explicit_checkpointer_contexts.pop(cache_key, None)
            _explicit_checkpointers.pop(cache_key, None)

    _explicit_checkpointers.clear()
    _explicit_checkpointer_contexts.clear()


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def checkpointer_context(app_config: AppConfig | None = None) -> Iterator[Checkpointer]:
    """Sync context manager that yields a checkpointer and cleans up on exit.

    Unlike :func:`get_checkpointer`, this does **not** cache the instance —
    each ``with`` block creates and destroys its own connection.  Use it in
    CLI scripts or tests where you want deterministic cleanup::

        with checkpointer_context() as cp:
            graph.invoke(input, config={"configurable": {"thread_id": "1"}})

    Yields an ``InMemorySaver`` when no checkpointer is configured in *config.yaml*.
    """

    resolved_app_config = app_config or get_app_config()
    if resolved_app_config.checkpointer is not None:
        with _sync_checkpointer_cm(resolved_app_config.checkpointer) as saver:
            yield saver
        return

    db_config = getattr(resolved_app_config, "database", None)
    if _persistent_database_backend(db_config) is not None:
        with _sync_checkpointer_from_database_cm(db_config) as saver:
            yield saver
        return

    yield _default_in_memory_checkpointer()
