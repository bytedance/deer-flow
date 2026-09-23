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

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig, ensure_config_loaded, get_checkpointer_config
from deerflow.persistence.postgres_schema import dsn_with_search_path, ensure_postgres_schema
from deerflow.runtime.checkpoint_mode import frozen_checkpoint_channel_mode
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
    ensure_postgres_schema(conn_string, schema, install_hint=POSTGRES_INSTALL)


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def _resolve_checkpointer_config(app_config: AppConfig) -> CheckpointerConfig:
    """Resolve the checkpointer backend from legacy or unified application config.

    The legacy ``checkpointer`` section remains authoritative when present so
    Checkpointer and Store keep using the same backend. Otherwise the unified
    ``database`` section drives the checkpointer, matching the async
    :func:`~deerflow.runtime.checkpointer.async_provider.make_checkpointer`
    factory and the sync Store provider's ``_resolve_store_config``.
    """
    if app_config.checkpointer is not None:
        return app_config.checkpointer

    database = app_config.database
    if database is None or database.backend == "memory":
        return CheckpointerConfig(type="memory")
    if database.backend == "sqlite":
        return CheckpointerConfig(type="sqlite", connection_string=database.checkpointer_sqlite_path)
    if database.backend == "postgres":
        if not database.postgres_url:
            raise ValueError("database.postgres_url is required for the postgres backend")
        return CheckpointerConfig(type="postgres", connection_string=database.postgres_url, postgres_schema=database.postgres_schema)
    raise ValueError(f"Unknown database backend: {database.backend!r}")


def _get_checkpointer_config() -> CheckpointerConfig:
    """Load checkpointer config without holding the provider singleton lock."""
    ensure_config_loaded()

    # Preserve callers that initialise the legacy config singleton directly.
    legacy_config = get_checkpointer_config()
    if legacy_config is not None:
        return legacy_config
    try:
        app_config = get_app_config()
    except FileNotFoundError:
        return CheckpointerConfig(type="memory")
    return _resolve_checkpointer_config(app_config)


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


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_checkpointer: Checkpointer | None = None
_checkpointer_ctx = None  # open context manager keeping the connection alive
_checkpointer_lock = threading.Lock()
_checkpointer_cache = None  # MemoryCheckpointHistoryCache singleton shared by wrapped sync savers
_checkpointer_cache_prefix: str | None = None  # key prefix the singleton was built for


def _wrap_sync_if_delta(saver: Checkpointer, app_config: AppConfig) -> Checkpointer:
    """Wrap *saver* in a delta-history cache when the effective mode is ``delta``.

    The process-frozen mode wins; ``database.checkpoint_channel_mode`` is the
    fallback when nothing is frozen yet. Only the memory cache backend is
    supported on the sync path (TUI/embedded) — it is process-local anyway.
    """
    global _checkpointer_cache, _checkpointer_cache_prefix
    # The ``_checkpointer_cache`` singleton is reassigned here without holding
    # ``_checkpointer_lock`` on the ``checkpointer_context()`` path (and under
    # the lock on the ``get_checkpointer()`` path). The race is intentional
    # and benign: worst case two wrappers get their own fresh memory cache —
    # last writer wins, and the cache is performance-only.
    db_config = getattr(app_config, "database", None)
    mode = frozen_checkpoint_channel_mode() or (db_config.checkpoint_channel_mode if db_config is not None else "full")
    if mode != "delta":
        return saver
    cache_config = app_config.database.checkpoint_cache
    if cache_config.type == "redis":
        raise ValueError("database.checkpoint_cache.type 'redis' is not supported on the sync checkpointer path (TUI/embedded); use 'memory'.")
    from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
    from deerflow.runtime.checkpoint_cache.provider import checkpoint_cache_key_prefix
    from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

    key_prefix = checkpoint_cache_key_prefix(app_config)
    # Recreate on capacity OR namespace change: entries under a stale prefix
    # would be unreachable and no longer covered by thread purges.
    if _checkpointer_cache is None or _checkpointer_cache._max_entries != cache_config.max_entries or _checkpointer_cache_prefix != key_prefix:
        _checkpointer_cache = MemoryCheckpointHistoryCache(max_entries=cache_config.max_entries)
        _checkpointer_cache_prefix = key_prefix
    return CachedHistorySaver(saver, _checkpointer_cache, key_prefix=key_prefix)


def get_checkpointer() -> Checkpointer:
    """Return the global sync checkpointer singleton, creating it on first call.

    The legacy ``checkpointer`` section takes precedence when configured;
    otherwise the unified ``database`` section selects the backend. Returns an
    ``InMemorySaver`` when neither selects a persistent backend.

    Raises:
        ImportError: If the required package for the configured backend is not installed.
        ValueError: If ``connection_string`` is missing for a backend that requires it.
    """
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    # Config loading can reset both persistence singletons. Resolve the full
    # config outside this provider lock to avoid cross-provider lock-order inversion.
    config = _get_checkpointer_config()

    # ``get_app_config()`` can trigger a config reload whose
    # ``_apply_singleton_configs`` calls ``reset_checkpointer()`` — which takes
    # ``_checkpointer_lock``. Resolve it (non-reentrant lock) BEFORE acquiring
    # the lock below, exactly like ``_get_checkpointer_config()`` above.
    try:
        app_config = get_app_config()
    except FileNotFoundError:
        app_config = None

    with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer

        checkpointer_ctx = _sync_checkpointer_cm(config)
        checkpointer = checkpointer_ctx.__enter__()
        try:
            if app_config is not None:
                checkpointer = _wrap_sync_if_delta(checkpointer, app_config)
        except Exception:
            checkpointer_ctx.__exit__(None, None, None)
            raise
        _checkpointer_ctx = checkpointer_ctx
        _checkpointer = checkpointer

    return _checkpointer


def reset_checkpointer() -> None:
    """Reset the sync singleton, forcing recreation on the next call.

    Closes any open backend connections and clears the cached instance.
    Useful in tests or after a configuration change.
    """
    global _checkpointer, _checkpointer_ctx, _checkpointer_cache, _checkpointer_cache_prefix
    with _checkpointer_lock:
        if _checkpointer_ctx is not None:
            try:
                _checkpointer_ctx.__exit__(None, None, None)
            except Exception:
                logger.warning("Error during checkpointer cleanup", exc_info=True)
            _checkpointer_ctx = None
        _checkpointer = None
        _checkpointer_cache = None
        _checkpointer_cache_prefix = None


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

    The legacy ``checkpointer`` section takes precedence when configured;
    otherwise the unified ``database`` section selects the backend. Yields an
    ``InMemorySaver`` when neither selects a persistent backend.
    """

    app_config = get_app_config()
    config = _resolve_checkpointer_config(app_config)
    with _sync_checkpointer_cm(config) as saver:
        yield _wrap_sync_if_delta(saver, app_config)
