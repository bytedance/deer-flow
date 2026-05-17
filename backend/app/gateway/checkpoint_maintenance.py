"""Maintenance helpers for LangGraph checkpoint storage.

These helpers intentionally live outside the router layer so startup
migrations and request handlers can share the same SQLite-specific
checkpointer maintenance behavior without depending on FastAPI.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def _sqlite_checkpoint_thread_ids(checkpointer: Any) -> list[str]:
    """Return checkpoint thread IDs using the SQLite saver connection when available.

    The public LangGraph checkpointer API can list checkpoints, but doing so
    deserializes checkpoint payloads. For migration/cleanup we only need the
    distinct thread IDs, so use the SQLite connection directly when the active
    saver exposes one.
    """
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return []

    setup = getattr(checkpointer, "setup", None)
    if setup is not None:
        result = setup()
        if inspect.isawaitable(result):
            await result

    lock = getattr(checkpointer, "lock", None)
    if lock is None:
        async with conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id") as cur:
            return [str(row[0]) async for row in cur]

    async with lock:
        async with conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id") as cur:
            return [str(row[0]) async for row in cur]


async def migrate_checkpoint_threads_to_thread_meta(
    checkpointer: Any,
    thread_store: Any,
    admin_user_id: str,
) -> int:
    """Create missing thread_meta rows for legacy checkpoint-only threads.

    Older DeerFlow installs could have valid LangGraph checkpoints without a
    corresponding ``threads_meta`` row. After search moved to ThreadMetaStore,
    those threads became invisible to the normal thread list and also failed
    strict destructive owner checks. Assigning these legacy rows to the first
    admin mirrors the existing no-auth-to-auth orphan migration.
    """
    migrated = 0
    for thread_id in await _sqlite_checkpoint_thread_ids(checkpointer):
        existing = await thread_store.get(thread_id, user_id=None)
        if existing is not None:
            continue
        try:
            await thread_store.create(
                thread_id,
                user_id=admin_user_id,
                metadata={"migrated_from": "legacy_checkpointer"},
            )
            migrated += 1
        except Exception:
            logger.debug("Could not create thread_meta for legacy checkpoint thread %s", thread_id, exc_info=True)
    return migrated


async def migrate_app_checkpoint_threads_to_thread_meta(app: Any, admin_user_id: str) -> int:
    """Migrate app-scoped legacy checkpoint threads when runtime state exists."""
    checkpointer = getattr(app.state, "checkpointer", None)
    thread_store = getattr(app.state, "thread_store", None)
    if checkpointer is None or thread_store is None:
        return 0
    return await migrate_checkpoint_threads_to_thread_meta(checkpointer, thread_store, admin_user_id)


async def _pragma_int(conn: Any, statement: str) -> int:
    async with conn.execute(statement) as cur:
        row = await cur.fetchone()
    return int(row[0])


async def compact_sqlite_checkpointer(
    checkpointer: Any,
    *,
    min_reclaimable_bytes: int = 64 * 1024 * 1024,
) -> bool:
    """Best-effort SQLite compaction after checkpoint deletes.

    LangGraph's SQLite saver deletes checkpoint rows, but SQLite keeps the file
    size until a VACUUM. Running this only when the active saver exposes a
    SQLite connection keeps postgres/memory backends as no-ops.
    """
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return False

    async def _execute(statement: str) -> None:
        async with conn.execute(statement) as cur:
            await cur.fetchall()

    async def _compact_if_worthwhile() -> bool:
        await conn.commit()
        await _execute("PRAGMA wal_checkpoint(TRUNCATE)")
        page_size = await _pragma_int(conn, "PRAGMA page_size")
        freelist_count = await _pragma_int(conn, "PRAGMA freelist_count")
        if page_size * freelist_count < min_reclaimable_bytes:
            return False
        await _execute("VACUUM")
        await conn.commit()
        await _execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await conn.commit()
        return True

    lock = getattr(checkpointer, "lock", None)
    if lock is None:
        return await _compact_if_worthwhile()

    async with lock:
        return await _compact_if_worthwhile()
