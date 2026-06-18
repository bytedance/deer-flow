"""Maintenance helpers for LangGraph checkpoint storage.

These helpers intentionally live outside the router layer so startup
migrations and request handlers can share the same SQLite-specific
checkpointer maintenance behavior without depending on FastAPI.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from pathlib import Path
from typing import Any

from deerflow.config.runtime_paths import runtime_home

logger = logging.getLogger(__name__)

_MIGRATION_TASK_STATE_ATTR = "checkpoint_thread_migration_task"


def _sqlite_saver_connection(checkpointer: Any) -> Any | None:
    """Return the aiosqlite connection only for LangGraph SQLite savers."""
    saver_type = type(checkpointer)
    type_name = saver_type.__name__.lower()
    module_name = saver_type.__module__.lower()
    if "sqlite" not in type_name or "langgraph.checkpoint.sqlite" not in module_name:
        return None

    conn = getattr(checkpointer, "conn", None)
    if conn is None or not hasattr(conn, "execute") or not hasattr(conn, "commit"):
        return None
    return conn


async def _ensure_checkpointer_setup(checkpointer: Any) -> None:
    setup = getattr(checkpointer, "setup", None)
    if setup is None:
        return
    result = setup()
    if inspect.isawaitable(result):
        await result


def _row_value(row: Any, index: int, key: str) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return row[index]


async def _sqlite_database_path(conn: Any) -> str | None:
    async with conn.execute("PRAGMA database_list") as cur:
        rows = await cur.fetchall()
    for row in rows:
        if _row_value(row, 1, "name") == "main":
            value = str(_row_value(row, 2, "file") or "")
            return value or None
    return None


async def _checkpoint_thread_migration_marker_path(conn: Any) -> Path | None:
    db_path = await _sqlite_database_path(conn)
    if not db_path:
        return None
    digest = hashlib.sha256(str(Path(db_path).expanduser().resolve()).encode()).hexdigest()[:16]
    return runtime_home() / "maintenance" / f"checkpoint-thread-meta-migration-{digest}.done"


def _write_migration_marker(marker_path: Path) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("completed\n", encoding="utf-8")


async def _sqlite_checkpoint_thread_ids(checkpointer: Any) -> list[str]:
    """Return checkpoint thread IDs using the SQLite saver connection when available.

    The public LangGraph checkpointer API can list checkpoints, but doing so
    deserializes checkpoint payloads. For migration/cleanup we only need the
    distinct thread IDs, so use the SQLite connection directly when the active
    saver exposes one.
    """
    conn = _sqlite_saver_connection(checkpointer)
    if conn is None:
        return []

    await _ensure_checkpointer_setup(checkpointer)

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
    strict destructive owner checks.

    Assigning these legacy rows to the first admin mirrors the existing
    no-auth-to-auth orphan migration. It is an ownership-recovery fallback for
    pre-auth single-owner installs, not a multi-tenant ownership audit tool.
    """
    conn = _sqlite_saver_connection(checkpointer)
    if conn is None:
        return 0

    await _ensure_checkpointer_setup(checkpointer)
    marker_path = await _checkpoint_thread_migration_marker_path(conn)
    if marker_path is not None and marker_path.exists():
        return 0

    migrated = 0
    failed = False
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
            failed = True
            logger.debug("Could not create thread_meta for legacy checkpoint thread %s", thread_id, exc_info=True)
    if marker_path is not None and not failed:
        _write_migration_marker(marker_path)
    return migrated


async def migrate_app_checkpoint_threads_to_thread_meta(app: Any, admin_user_id: str) -> int:
    """Migrate app-scoped legacy checkpoint threads when runtime state exists."""
    checkpointer = getattr(app.state, "checkpointer", None)
    thread_store = getattr(app.state, "thread_store", None)
    if checkpointer is None or thread_store is None:
        return 0
    return await migrate_checkpoint_threads_to_thread_meta(checkpointer, thread_store, admin_user_id)


def schedule_app_checkpoint_thread_migration(app: Any, admin_user_id: str) -> bool:
    """Schedule legacy checkpoint thread migration without blocking startup/setup."""
    existing_task = getattr(app.state, _MIGRATION_TASK_STATE_ATTR, None)
    if existing_task is not None and not existing_task.done():
        return False

    async def _run() -> None:
        try:
            migrated = await migrate_app_checkpoint_threads_to_thread_meta(app, admin_user_id)
            if migrated:
                logger.info("Migrated %d legacy checkpoint thread(s) to admin thread metadata", migrated)
        except Exception:
            logger.exception("Legacy checkpoint thread migration failed (non-fatal)")

    task = asyncio.create_task(_run(), name="deerflow-checkpoint-thread-migration")
    setattr(app.state, _MIGRATION_TASK_STATE_ATTR, task)
    return True


async def _pragma_int(conn: Any, statement: str) -> int:
    async with conn.execute(statement) as cur:
        row = await cur.fetchone()
    return int(row[0])


async def compact_sqlite_checkpointer(
    checkpointer: Any,
    *,
    min_reclaimable_bytes: int = 64 * 1024 * 1024,
    min_reclaimable_ratio: float = 0.10,
    max_database_bytes: int = 2 * 1024 * 1024 * 1024,
) -> bool:
    """Best-effort SQLite compaction after checkpoint deletes.

    LangGraph's SQLite saver deletes checkpoint rows, but SQLite keeps the file
    size until a VACUUM. Running this only when the active saver exposes a
    SQLite connection keeps postgres/memory backends as no-ops. Automatic
    compaction is intentionally conservative because VACUUM rewrites the whole
    database; large stores should use the explicit maintenance CLI instead.
    """
    conn = _sqlite_saver_connection(checkpointer)
    if conn is None:
        return False

    async def _execute(statement: str) -> None:
        async with conn.execute(statement) as cur:
            await cur.fetchall()

    async def _compact_if_worthwhile() -> bool:
        await conn.commit()
        await _execute("PRAGMA wal_checkpoint(TRUNCATE)")
        page_size = await _pragma_int(conn, "PRAGMA page_size")
        page_count = await _pragma_int(conn, "PRAGMA page_count")
        freelist_count = await _pragma_int(conn, "PRAGMA freelist_count")
        reclaimable_bytes = page_size * freelist_count
        database_bytes = page_size * page_count
        reclaimable_ratio = freelist_count / page_count if page_count else 0
        if reclaimable_bytes < min_reclaimable_bytes:
            return False
        if reclaimable_ratio < min_reclaimable_ratio:
            return False
        if database_bytes > max_database_bytes:
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
