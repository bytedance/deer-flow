"""Provider-aware publication of authoritative upload paths to sandboxes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deerflow.uploads.async_helpers import run_upload_io_cancellation_safe, wait_for_task_completion
from deerflow.uploads.manager import make_upload_file_sandbox_readable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SandboxSyncReceipt:
    """Remote paths created by one completed sandbox synchronization."""

    sandbox: Any | None
    virtual_paths: tuple[str, ...] = ()


def _make_paths_readable(paths: tuple[tuple[Path, str], ...]) -> None:
    for physical_path, _ in paths:
        make_upload_file_sandbox_readable(physical_path)


def _remove_remote_paths(sandbox: Any, virtual_paths: tuple[str, ...]) -> None:
    first_error: BaseException | None = None
    seen: set[str] = set()
    for virtual_path in reversed(virtual_paths):
        if virtual_path in seen:
            continue
        seen.add(virtual_path)
        try:
            sandbox.remove_file(virtual_path)
        except BaseException as exc:
            if first_error is None:
                first_error = exc
            logger.warning("Failed to remove synchronized sandbox upload: %s", virtual_path, exc_info=True)
    if first_error is not None:
        raise first_error


def rollback_sandbox_sync(receipt: SandboxSyncReceipt) -> None:
    """Remove every exact remote path recorded by *receipt*."""
    if receipt.sandbox is not None and receipt.virtual_paths:
        _remove_remote_paths(receipt.sandbox, receipt.virtual_paths)


def _sync_remote_paths(sandbox: Any, paths: tuple[tuple[Path, str], ...]) -> SandboxSyncReceipt:
    attempted: list[str] = []
    completed: list[str] = []
    try:
        for physical_path, virtual_path in paths:
            attempted.append(virtual_path)
            sandbox.update_file(virtual_path, physical_path.read_bytes())
            completed.append(virtual_path)
    except BaseException:
        try:
            _remove_remote_paths(sandbox, tuple(attempted))
        except BaseException:
            pass
        raise
    return SandboxSyncReceipt(sandbox=sandbox, virtual_paths=tuple(completed))


def make_upload_paths_available(
    sandbox_provider: Any,
    thread_id: str,
    *,
    user_id: str | None,
    paths: list[tuple[Path, str]],
) -> SandboxSyncReceipt:
    """Synchronously make exact host upload paths available to one provider."""
    sync_paths = tuple((Path(path), virtual_path) for path, virtual_path in paths)
    if getattr(sandbox_provider, "uses_thread_data_mounts", False):
        _make_paths_readable(sync_paths)
        return SandboxSyncReceipt(sandbox=None)

    sandbox_id = sandbox_provider.acquire(thread_id, user_id=user_id)
    sandbox = sandbox_provider.get(sandbox_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {sandbox_id!r} not found after acquire")
    return _sync_remote_paths(sandbox, sync_paths)


async def make_upload_paths_available_async(
    sandbox_provider: Any,
    thread_id: str,
    *,
    user_id: str | None,
    paths: list[tuple[Path, str]],
) -> SandboxSyncReceipt:
    """Cancellation-safely expose exact upload paths to a mounted or remote sandbox."""
    sync_paths = tuple((Path(path), virtual_path) for path, virtual_path in paths)
    if getattr(sandbox_provider, "uses_thread_data_mounts", False):
        await run_upload_io_cancellation_safe(_make_paths_readable, sync_paths)
        return SandboxSyncReceipt(sandbox=None)

    sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=user_id)
    sandbox = sandbox_provider.get(sandbox_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {sandbox_id!r} not found after acquire")

    sync_task = asyncio.create_task(
        asyncio.to_thread(_sync_remote_paths, sandbox, sync_paths),
        name=f"sync-upload-paths:{thread_id}",
    )
    cancelled = await wait_for_task_completion(sync_task)
    receipt = sync_task.result()
    if cancelled:
        cleanup_task = asyncio.create_task(
            asyncio.to_thread(rollback_sandbox_sync, receipt),
            name=f"rollback-sandbox-upload-paths:{thread_id}",
        )
        await wait_for_task_completion(cleanup_task)
        try:
            cleanup_task.result()
        except BaseException:
            logger.warning("Failed to roll back sandbox uploads after cancellation", exc_info=True)
        raise asyncio.CancelledError
    return receipt
