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
import threading
from collections.abc import Iterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig, ensure_config_loaded
from deerflow.persistence.postgres_schema import create_schema_sql, dsn_with_search_path
from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir, resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error message constants — imported by aio.provider too
# ---------------------------------------------------------------------------

SQLITE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite checkpointer. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_INSTALL = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install the package extra with: pip install 'deerflow-harness[postgres]' (or use: uv sync --all-packages --extra postgres when developing locally)"
)
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"


def _ensure_postgres_schema(conn_string: str, schema: str) -> None:
    """Create the configured schema before LangGraph creates its tables."""
    statement = create_schema_sql(schema)
    if statement is None:
        return
    try:
        import psycopg
    except ImportError as exc:
        raise ImportError(POSTGRES_INSTALL) from exc

    with psycopg.connect(conn_string, autocommit=True) as conn:
        conn.execute(statement)


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

        _ensure_postgres_schema(config.connection_string, config.postgres_schema)
        conn_string = dsn_with_search_path(config.connection_string, config.postgres_schema)
        with PostgresSaver.from_conn_string(conn_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


@contextlib.contextmanager
def _sync_checkpointer_from_database(db_config) -> Iterator[Checkpointer]:
    """Context manager that creates a sync checkpointer from DatabaseConfig."""
    if db_config.backend == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    if db_config.backend == "sqlite":
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

    if db_config.backend == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not db_config.postgres_url:
            raise ValueError("database.postgres_url is required for the postgres backend")

        _ensure_postgres_schema(db_config.postgres_url, db_config.postgres_schema)
        conn_string = dsn_with_search_path(db_config.postgres_url, db_config.postgres_schema)
        with PostgresSaver.from_conn_string(conn_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown database backend: {db_config.backend!r}")


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_checkpointer: Checkpointer | None = None
_checkpointer_ctx = None  # open context manager keeping the connection alive
_checkpointer_lock = threading.Lock()


def get_checkpointer() -> Checkpointer:
    """Return the global sync checkpointer singleton, creating it on first call.

    Returns an ``InMemorySaver`` when no checkpointer is configured in *config.yaml*.

    Raises:
        ImportError: If the required package for the configured backend is not installed.
        ValueError: If ``connection_string`` is missing for a backend that requires it.
    """
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    # Config loading can reset both persistence singletons. Keep it outside
    # this provider lock to avoid cross-provider lock-order inversion.
    ensure_config_loaded()

    with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer

        from deerflow.config.checkpointer_config import get_checkpointer_config

        config = get_checkpointer_config()

        if config is None:
            try:
                app_config = get_app_config()
            except FileNotFoundError:
                app_config = None
            db_config = getattr(app_config, "database", None) if app_config is not None else None
            if db_config is not None and db_config.backend != "memory":
                checkpointer_ctx = _sync_checkpointer_from_database(db_config)
                checkpointer = checkpointer_ctx.__enter__()
                _checkpointer_ctx = checkpointer_ctx
                _checkpointer = checkpointer
                return _checkpointer

            from langgraph.checkpoint.memory import InMemorySaver

            logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
            _checkpointer = InMemorySaver()
            return _checkpointer

        checkpointer_ctx = _sync_checkpointer_cm(config)
        checkpointer = checkpointer_ctx.__enter__()
        _checkpointer_ctx = checkpointer_ctx
        _checkpointer = checkpointer

    return _checkpointer


def reset_checkpointer() -> None:
    """Reset the sync singleton, forcing recreation on the next call.

    Closes any open backend connections and clears the cached instance.
    Useful in tests or after a configuration change.
    """
    global _checkpointer, _checkpointer_ctx
    with _checkpointer_lock:
        if _checkpointer_ctx is not None:
            try:
                _checkpointer_ctx.__exit__(None, None, None)
            except Exception:
                logger.warning("Error during checkpointer cleanup", exc_info=True)
            _checkpointer_ctx = None
        _checkpointer = None


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def checkpointer_context() -> Iterator[Checkpointer]:
    """Sync context manager that yields a checkpointer and cleans up on exit.

    Unlike :func:`get_checkpointer`, this does **not** cache the instance —
    each ``with`` block creates and destroys its own connection.  Use it in
    CLI scripts or tests where you want deterministic cleanup::

        with checkpointer_context() as cp:
            graph.invoke(input, config={"configurable": {"thread_id": "1"}})

    Yields an ``InMemorySaver`` when no checkpointer is configured in *config.yaml*.
    """

    config = get_app_config()
    if config.checkpointer is not None:
        with _sync_checkpointer_cm(config.checkpointer) as saver:
            yield saver
            return

    db_config = getattr(config, "database", None)
    if db_config is not None and db_config.backend != "memory":
        with _sync_checkpointer_from_database(db_config) as saver:
            yield saver
            return

    from langgraph.checkpoint.memory import InMemorySaver

    yield InMemorySaver()
