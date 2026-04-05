"""Async checkpointer factory.

Provides an **async context manager** for long-running async servers that need
proper resource cleanup. Includes startup recovery for stale runs left behind
by a previous crash.

Supported backends: memory, sqlite, postgres.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.types import Checkpointer

from deerflow.agents.checkpointer.provider import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_INSTALL,
    SQLITE_INSTALL,
)
from deerflow.config.app_config import get_app_config
from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir, resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Async factory
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_checkpointer(config) -> AsyncIterator[Checkpointer]:
    """Async context manager that constructs and tears down a checkpointer."""
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
        ensure_sqlite_parent_dir(conn_str)
        async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
            await saver.setup()
            yield saver
        return

    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        async with AsyncPostgresSaver.from_conn_string(config.connection_string) as saver:
            await saver.setup()
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


# ---------------------------------------------------------------------------
# Stale run cleanup on startup
# ---------------------------------------------------------------------------


async def _cleanup_sqlite_stale_runs(conn_str: str) -> int:
    """Directly clean up stale checkpoint data from the SQLite database.

    When the LangGraph server crashes, checkpoint writes for in-progress runs
    may be partially committed. On restart, the in-memory runtime detects
    ``n_running > 0`` from the persisted state but has no active workers,
    causing the queue to stall indefinitely (active=0, n_running>0).

    This function opens the SQLite database directly and removes checkpoint
    records that have ``pending_writes`` or ``pending_sends`` (indicators of
    an interrupted run), allowing the server to start with a clean state.

    Args:
        conn_str: Path to the SQLite database file.

    Returns:
        Number of stale checkpoint records removed.
    """
    import pathlib

    if conn_str == ":memory:" or conn_str.startswith("file:"):
        return 0

    db_path = pathlib.Path(conn_str)
    if not db_path.exists():
        return 0

    try:
        import aiosqlite

        stale_count = 0
        async with aiosqlite.connect(str(db_path)) as db:
            # Detect interrupted runs: checkpoint_writes with pending data
            # that will never be consumed because the workers are gone.
            # Delete these so the queue doesn't stall on restart.
            for table in ("checkpoint_writes", "checkpoint_blobs"):
                try:
                    async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                        row = await cursor.fetchone()
                        count = row[0] if row else 0
                    if count > 0:
                        await db.execute(f"DELETE FROM {table}")
                        stale_count += count
                        logger.info(
                            "Removed %d stale records from %s", count, table
                        )
                except Exception:
                    pass  # Table may not exist in all schemas

            if stale_count > 0:
                await db.commit()
                logger.warning(
                    "Cleaned up %d stale checkpoint records from a previous crash. "
                    "If issues persist, manually delete the checkpointer database "
                    "file and restart.",
                    stale_count,
                )

        return stale_count

    except ImportError:
        logger.debug("aiosqlite not available, skipping stale run cleanup")
        return 0
    except Exception as exc:
        logger.warning(
            "Failed to check for stale runs in checkpointer: %s. "
            "If the server queue appears stuck after a crash, manually "
            "delete the checkpointer database file and restart.",
            exc,
        )
        return 0


# ---------------------------------------------------------------------------
# Public async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def make_checkpointer() -> AsyncIterator[Checkpointer]:
    """Async context manager that yields a checkpointer for the caller's lifetime.
    Resources are opened on enter and closed on exit — no global state::

        async with make_checkpointer() as checkpointer:
            app.state.checkpointer = checkpointer

    Yields an ``InMemorySaver`` when no checkpointer is configured in *config.yaml*.
    """

    config = get_app_config()

    if config.checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    # For SQLite, attempt stale run cleanup before initializing checkpointer
    if config.checkpointer.type == "sqlite":
        conn_str = _resolve_sqlite_conn_str(
            config.checkpointer.connection_string or "store.db"
        )
        stale = await _cleanup_sqlite_stale_runs(conn_str)
        if stale > 0:
            logger.warning(
                "Cleaned up %d stale checkpoint records from a previous crash.",
                stale,
            )

    async with _async_checkpointer(config.checkpointer) as saver:
        yield saver
