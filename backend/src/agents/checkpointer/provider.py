"""Sync checkpointer factory.

Provides a **sync singleton** and a **sync context manager** for LangGraph
graph compilation and CLI tools.

Supported backends: memory, sqlite, postgres.

Usage::

    from src.agents.checkpointer.provider import get_checkpointer, checkpointer_context

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

from src.config.app_config import get_app_config
from src.config.checkpointer_config import CheckpointerConfig
from src.config.paths import resolve_path

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


def _make_sync_checkpointer(config: CheckpointerConfig) -> Checkpointer:
    """Build a sync checkpointer for *config*.

    Returns ``(saver, cleanup_fn)`` where *cleanup_fn* closes the underlying
    connection/pool, or ``None`` when no cleanup is required (e.g. memory).
    """
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
        return InMemorySaver()

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = resolve_path(config.connection_string or "store.db")
        with SqliteSaver.from_conn_string(conn_str) as saver:
            saver.setup()
            logger.info("Checkpointer: using SqliteSaver (%s)", conn_str)
            return saver

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
            return saver

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------

_checkpointer: Checkpointer = None


def get_checkpointer() -> Checkpointer | None:
    """Return the global sync checkpointer singleton, creating it on first call.

    Returns ``None`` when no checkpointer is configured in *config.yaml*.

    Raises:
        ImportError: If the required package for the configured backend is not installed.
        ValueError: If ``connection_string`` is missing for a backend that requires it.
    """
    global _checkpointer

    if _checkpointer is not None:
        return _checkpointer

    from src.config.checkpointer_config import get_checkpointer_config

    config = get_checkpointer_config()
    if config is None:
        return None

    _checkpointer = _make_sync_checkpointer(config)

    return _checkpointer


def reset_checkpointer() -> None:
    """Reset the sync singleton, forcing recreation on the next call.

    Useful in tests or after a configuration change.
    """
    global _checkpointer
    _checkpointer = None


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def checkpointer_context() -> Iterator[Checkpointer | None]:
    """Sync context manager that yields a checkpointer and cleans up on exit.

    Unlike :func:`get_checkpointer`, this does **not** cache the instance —
    each ``with`` block creates and destroys its own connection.  Use it in
    CLI scripts or tests where you want deterministic cleanup::

        with checkpointer_context() as cp:
            graph.invoke(input, config={"configurable": {"thread_id": "1"}})
    """

    config = get_app_config()
    if config.checkpointer is None:
        yield None
        return

    saver = _make_sync_checkpointer(config.checkpointer)
    yield saver
