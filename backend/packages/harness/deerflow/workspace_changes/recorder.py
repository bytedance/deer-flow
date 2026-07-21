from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from deerflow.config import get_paths

from .diff import compare_snapshots, get_changed_paths
from .scanner import scan_workspace_roots
from .types import (
    WORKSPACE_CHANGES_EVENT_TYPE,
    WORKSPACE_CHANGES_METADATA_KEY,
    WorkspaceChangeLimits,
    WorkspaceRoot,
    WorkspaceSnapshot,
)

logger = logging.getLogger(__name__)


def build_thread_workspace_roots(thread_id: str, *, user_id: str | None = None) -> list[WorkspaceRoot]:
    paths = get_paths()
    return [
        WorkspaceRoot(
            name="workspace",
            host_path=paths.sandbox_work_dir(thread_id, user_id=user_id),
            virtual_prefix="/mnt/user-data/workspace",
        ),
        WorkspaceRoot(
            name="outputs",
            host_path=paths.sandbox_outputs_dir(thread_id, user_id=user_id),
            virtual_prefix="/mnt/user-data/outputs",
        ),
    ]


def _prepare_capture(thread_id: str, *, user_id: str | None, include_text: bool) -> tuple[list[WorkspaceRoot], Path | None]:
    # Worker thread: resolving the sandbox roots hits the filesystem, and mkdtemp
    # creates the text cache directory — both blocking IO that must stay off the
    # event loop.
    roots = build_thread_workspace_roots(thread_id, user_id=user_id)
    text_cache_dir = Path(tempfile.mkdtemp(prefix="deerflow-workspace-changes-")) if include_text else None
    return roots, text_cache_dir


async def _remove_text_cache_dir(text_cache_dir: str | Path) -> None:
    """Remove a snapshot's text cache off the event loop.

    Best-effort by contract: every caller is a failure or teardown path, so a
    cleanup error must never replace the exception or result already in flight.
    """
    try:
        await asyncio.to_thread(shutil.rmtree, text_cache_dir, ignore_errors=True)
    except Exception:
        logger.warning("Failed to remove workspace text cache %s", text_cache_dir, exc_info=True)


async def _reclaim_prepare_and_cleanup(prepare: asyncio.Future[tuple[list[WorkspaceRoot], Path | None]]) -> None:
    """Await a cancelled prepare handoff and remove any dir it created.

    Owned by its own task so that caller cancellation during reclaim can interrupt
    the *await* but never abandon a just-created text cache dir. Best-effort,
    mirroring `_remove_text_cache_dir`.
    """
    try:
        _, orphaned = await prepare
    except Exception:
        return  # prepare failed before creating a dir; nothing to reclaim
    if orphaned is not None:
        await _remove_text_cache_dir(orphaned)


async def capture_workspace_snapshot(
    thread_id: str,
    *,
    user_id: str | None = None,
    limits: WorkspaceChangeLimits | None = None,
    include_text: bool = True,
) -> WorkspaceSnapshot:
    # `_prepare_capture` creates the text cache dir inside the worker, so the
    # handoff must be cancellation-safe: if the run is cancelled after mkdtemp
    # but before we receive the path, the shielded worker still finishes and we
    # reclaim its result to remove the orphaned dir before re-raising.
    prepare = asyncio.ensure_future(asyncio.to_thread(_prepare_capture, thread_id, user_id=user_id, include_text=include_text))
    try:
        roots, text_cache_dir = await asyncio.shield(prepare)
    except asyncio.CancelledError:
        # `prepare` is shielded, so it keeps running and may still create the dir
        # after this cancel. Own the reclaim+remove in a task the caller cannot
        # abandon: a repeat cancel can interrupt our await but not the task, so we
        # drain repeated cancellation until cleanup finishes, then restore it. A
        # second `shield()` on the await alone would let a re-cancel skip the
        # reclaim and orphan the dir.
        cleanup = asyncio.ensure_future(_reclaim_prepare_and_cleanup(prepare))
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                pass
        raise
    try:
        return await asyncio.to_thread(
            scan_workspace_roots,
            roots,
            limits=limits,
            include_text=include_text,
            text_cache_dir=text_cache_dir,
        )
    except Exception:
        if text_cache_dir is not None:
            await _remove_text_cache_dir(text_cache_dir)
        raise


async def record_workspace_changes(
    event_store: Any,
    thread_id: str,
    run_id: str,
    before: WorkspaceSnapshot,
    *,
    user_id: str | None = None,
    limits: WorkspaceChangeLimits | None = None,
) -> dict | None:
    try:
        roots = await asyncio.to_thread(build_thread_workspace_roots, thread_id, user_id=user_id)
        after_metadata = await asyncio.to_thread(
            scan_workspace_roots,
            roots,
            limits=limits,
            include_text=False,
        )
        changed_paths = get_changed_paths(before, after_metadata)
        after = await asyncio.to_thread(
            scan_workspace_roots,
            roots,
            limits=limits,
            include_text=True,
            text_paths=changed_paths,
        )
        result = compare_snapshots(before, after, limits=limits)
        if not result.has_changes():
            return None

        payload = result.to_dict()
        summary = result.summary
        changed_file_count = summary.created + summary.modified + summary.deleted + summary.symlink_created
        content = f"{changed_file_count} file{'s' if changed_file_count != 1 else ''} changed +{summary.additions} -{summary.deletions}"
        return await event_store.put(
            thread_id=thread_id,
            run_id=run_id,
            event_type=WORKSPACE_CHANGES_EVENT_TYPE,
            category="workspace",
            content=content,
            metadata={WORKSPACE_CHANGES_METADATA_KEY: payload},
        )
    finally:
        await _cleanup_snapshot_text_cache(before)


async def _cleanup_snapshot_text_cache(snapshot: WorkspaceSnapshot) -> None:
    if snapshot.text_cache_dir:
        await _remove_text_cache_dir(snapshot.text_cache_dir)
