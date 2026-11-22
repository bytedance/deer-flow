"""Reclaim old queue attachment stages that are no longer needed."""

import logging
import os
import shutil
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from time import time

from app.gateway.run_input_files import QUEUED_UPLOADS_DIR, is_staging_id
from deerflow.config.paths import Paths
from deerflow.runtime.runs.store.base import RunStore
from deerflow.uploads.manager import UPLOAD_STAGING_MIN_AGE
from deerflow.utils.file_io import await_drained, run_file_io
from deerflow.utils.host_paths import extended_length_path

logger = logging.getLogger(__name__)


def _directory_stat(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return info
    return None


def _directories(path: Path) -> Iterator[tuple[Path, os.stat_result]]:
    if _directory_stat(path) is None:
        return
    try:
        for child in path.iterdir():
            if (info := _directory_stat(child)) is not None:
                yield child, info
    except (FileNotFoundError, NotADirectoryError):
        return


def _find_stale_stages(paths: Paths, cutoff: float) -> dict[tuple[str, str], list[tuple[Path, os.stat_result]]]:
    candidates = {}
    for owner_dir, _ in _directories(extended_length_path(paths.base_dir / "users")):
        for thread_dir, _ in _directories(owner_dir / "threads"):
            scope = owner_dir.name, thread_dir.name
            try:
                paths.thread_dir(scope[1], user_id=scope[0])
            except ValueError:
                continue  # A queued attachment cannot have been staged here.
            stages = [(path, info) for path, info in _directories(thread_dir / QUEUED_UPLOADS_DIR) if is_staging_id(path.name) and info.st_mtime < cutoff]
            if stages:
                candidates[scope] = stages
    return candidates


def _remove_stale_stages(candidates: list[tuple[Path, os.stat_result]], cutoff: float) -> int:
    removed = 0
    for path, original in candidates:
        try:
            current = _directory_stat(path)
            if current is None or current.st_mtime >= cutoff or current.st_ctime_ns != original.st_ctime_ns:
                continue
            if not current.st_ino or not os.path.samestat(original, current):
                continue
            shutil.rmtree(path)
            removed += 1
        except FileNotFoundError:
            pass  # A peer startup sweep or thread deletion already removed it.
        except OSError:
            logger.warning("Failed to remove abandoned queued upload stage", exc_info=True)
    return removed


async def cleanup_abandoned_queued_uploads(store: RunStore, paths: Paths) -> int:
    cutoff = time() - UPLOAD_STAGING_MIN_AGE.total_seconds()
    candidates = await run_file_io(_find_stale_stages, paths, cutoff)
    if not candidates:
        return 0

    # Discover directories before reading active rows. A peer may have staged
    # bytes but still be committing its input. If its source is active, keep
    # the directory. Otherwise the commit either preceded the terminal status
    # and will be visible in the receipt read below, or can no longer succeed.
    # Include active rows even when a peer clock put their timestamp in the future.
    active = await store.list_inflight(before=datetime.max.replace(tzinfo=UTC).isoformat())
    active_scopes = {((row.get("user_id") or "").lower(), row["thread_id"].lower()) for row in active}
    removed = 0
    for (owner_id, thread_id), stages in candidates.items():
        if (owner_id.lower(), thread_id.lower()) in active_scopes:
            continue
        runs = await store.list_input_runs(thread_id, user_id=owner_id, limit=None, ignore_scope_case=True)
        # A dispatch receipt can be applied before the files reach the sandbox.
        receipts = (item for run in runs for item in (run.get("run_inputs") or {}).get("items", []))
        referenced = {stage.get("id") for item in receipts if (stage := item.get("attachment_stage")) and item.get("status") != "cancelled" and stage.get("published") is not True}
        orphaned = [(path, info) for path, info in stages if path.name not in referenced]
        if orphaned:
            removed += await await_drained(run_file_io(_remove_stale_stages, orphaned, cutoff))
    return removed
