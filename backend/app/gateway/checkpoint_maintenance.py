"""Maintenance helpers for LangGraph checkpoint storage."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import shutil
from pathlib import Path
from typing import Any

from deerflow.config.paths import Paths, get_paths
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
    """Return distinct checkpoint thread IDs from a LangGraph SQLite saver."""
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


async def _checkpoint_title(checkpointer: Any, thread_id: str) -> str | None:
    aget_tuple = getattr(checkpointer, "aget_tuple", None)
    if aget_tuple is None:
        return None
    try:
        checkpoint_tuple = await aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    except Exception:
        logger.debug("Could not read checkpoint title for legacy thread %s", thread_id, exc_info=True)
        return None
    if checkpoint_tuple is None:
        return None

    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    title = checkpoint.get("channel_values", {}).get("title")
    if isinstance(title, str) and title.strip():
        return title
    return None


def _copy_legacy_thread_dir(paths: Paths, thread_id: str, user_id: str) -> bool:
    """Copy legacy thread data into the user-scoped layout without overwrites."""
    legacy_dir = paths.thread_dir(thread_id)
    if not legacy_dir.exists():
        return False

    target_dir = paths.thread_dir(thread_id, user_id=user_id)
    if not target_dir.exists():
        shutil.copytree(legacy_dir, target_dir)
        paths.ensure_thread_dirs(thread_id, user_id=user_id)
        return True

    copied = False
    for source in legacy_dir.rglob("*"):
        relative = source.relative_to(legacy_dir)
        target = target_dir / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied = True

    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    return copied


async def _migrate_checkpoint_thread_ids(
    checkpointer: Any,
    thread_store: Any,
    admin_user_id: str,
    thread_ids: list[str],
    *,
    paths: Paths | None = None,
) -> tuple[int, bool]:
    paths = paths or get_paths()
    migrated = 0
    failed = False

    for thread_id in thread_ids:
        try:
            existing = await thread_store.get(thread_id, user_id=None)
        except Exception:
            failed = True
            logger.debug("Could not read thread_meta for legacy checkpoint thread %s", thread_id, exc_info=True)
            continue

        try:
            if existing is None:
                await thread_store.create(
                    thread_id,
                    user_id=admin_user_id,
                    display_name=await _checkpoint_title(checkpointer, thread_id),
                    metadata={"migrated_from": "legacy_checkpointer"},
                )
                migrated += 1

            owner_id = admin_user_id if existing is None else existing.get("user_id")
            if owner_id == admin_user_id:
                _copy_legacy_thread_dir(paths, thread_id, admin_user_id)
        except Exception:
            failed = True
            logger.debug("Could not migrate legacy checkpoint thread %s", thread_id, exc_info=True)

    return migrated, failed


async def migrate_checkpoint_threads_to_thread_meta(
    checkpointer: Any,
    thread_store: Any,
    admin_user_id: str,
) -> int:
    """Create missing thread_meta rows for legacy SQLite checkpoint threads.

    Older DeerFlow installs could have valid LangGraph checkpoints and legacy
    ``threads/<thread_id>/user-data`` files without a corresponding
    ``threads_meta`` row. After thread search moved to ``ThreadMetaStore`` and
    artifacts became user-scoped, those threads disappeared from the UI and
    their artifact links resolved under the wrong directory.

    Assigning recovered rows to the first admin mirrors the existing no-auth to
    auth orphan migration for pre-auth single-user installs.
    """
    conn = _sqlite_saver_connection(checkpointer)
    if conn is None:
        return 0

    await _ensure_checkpointer_setup(checkpointer)
    marker_path = await _checkpoint_thread_migration_marker_path(conn)
    if marker_path is not None and marker_path.exists():
        return 0

    migrated, failed = await _migrate_checkpoint_thread_ids(
        checkpointer,
        thread_store,
        admin_user_id,
        await _sqlite_checkpoint_thread_ids(checkpointer),
    )

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
    """Schedule legacy checkpoint thread migration without blocking setup."""
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
