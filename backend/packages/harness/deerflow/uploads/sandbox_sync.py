"""Provider-aware publication of authoritative upload paths to sandboxes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deerflow.sandbox.sandbox_provider import (
    sandbox_provider_sandbox_uses_thread_data_mounts,
    sandbox_provider_uses_thread_data_mounts,
    sandbox_provider_uses_thread_data_mounts_async,
)
from deerflow.uploads.async_helpers import run_upload_io_cancellation_safe, wait_for_task_completion
from deerflow.uploads.layout import conversion_virtual_path
from deerflow.uploads.manager import (
    RemoteDeletionCommitRequiredError,
    make_upload_file_sandbox_readable,
    upload_virtual_path,
)

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


def _deletion_hook_for_sandbox(
    sandbox: Any,
) -> Callable[[str, Path, Path | None], None]:
    def delete_remote_copy(
        filename: str,
        primary_path: Path,
        conversion_path: Path | None,
    ) -> None:
        targets = (
            (upload_virtual_path(filename), primary_path.read_bytes()),
            (
                conversion_virtual_path(filename),
                conversion_path.read_bytes() if conversion_path is not None else None,
            ),
        )
        removed: list[tuple[str, bytes | None]] = []
        for virtual_path, authoritative_bytes in targets:
            try:
                sandbox.remove_file(virtual_path)
            except BaseException as delete_error:
                # A remote failure is ambiguous: the server may have removed
                # the file before the client observed the error.  Re-publish
                # the current target and every prior success from the staged
                # authoritative bytes before allowing the host rollback.
                compensation_failed = False
                for rollback_path, rollback_bytes in reversed([*removed, (virtual_path, authoritative_bytes)]):
                    if rollback_bytes is None:
                        continue
                    try:
                        sandbox.update_file(rollback_path, rollback_bytes)
                    except BaseException:
                        compensation_failed = True
                        logger.warning(
                            "Failed to compensate partially deleted sandbox upload: %s",
                            rollback_path,
                            exc_info=True,
                        )
                if compensation_failed:
                    raise RemoteDeletionCommitRequiredError("Remote upload deletion could not be compensated") from delete_error
                raise
            removed.append((virtual_path, authoritative_bytes))

    return delete_remote_copy


def prepare_upload_deletion(
    sandbox_provider: Any,
    thread_id: str,
    *,
    user_id: str | None,
) -> Callable[[str, Path, Path | None], None] | None:
    """Return a lease-safe remote deletion hook for an explicitly synced sandbox."""
    if sandbox_provider_uses_thread_data_mounts(sandbox_provider):
        return None
    sandbox_id = sandbox_provider.acquire(thread_id, user_id=user_id)
    if sandbox_provider_sandbox_uses_thread_data_mounts(sandbox_provider, sandbox_id):
        return None
    sandbox = sandbox_provider.get(sandbox_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {sandbox_id!r} not found after acquire")
    return _deletion_hook_for_sandbox(sandbox)


async def prepare_upload_deletion_async(
    sandbox_provider: Any,
    thread_id: str,
    *,
    user_id: str | None,
) -> Callable[[str, Path, Path | None], None] | None:
    """Async counterpart that keeps remote acquisition off the event loop."""
    if await sandbox_provider_uses_thread_data_mounts_async(sandbox_provider):
        return None
    sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=user_id)
    if sandbox_provider_sandbox_uses_thread_data_mounts(sandbox_provider, sandbox_id):
        return None
    sandbox = sandbox_provider.get(sandbox_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {sandbox_id!r} not found after acquire")
    return _deletion_hook_for_sandbox(sandbox)


def rollback_sandbox_sync(receipt: SandboxSyncReceipt) -> None:
    """Remove every exact remote path recorded by *receipt*."""
    if receipt.sandbox is not None and receipt.virtual_paths:
        _remove_remote_paths(receipt.sandbox, receipt.virtual_paths)


async def rollback_sandbox_sync_async(receipt: SandboxSyncReceipt) -> None:
    """Cancellation-safely remove every remote path recorded by *receipt*."""
    cleanup_task = asyncio.create_task(
        asyncio.to_thread(rollback_sandbox_sync, receipt),
        name="rollback-sandbox-upload-paths",
    )
    await wait_for_task_completion(cleanup_task)
    cleanup_task.result()


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
    if sandbox_provider_uses_thread_data_mounts(sandbox_provider):
        _make_paths_readable(sync_paths)
        return SandboxSyncReceipt(sandbox=None)

    sandbox_id = sandbox_provider.acquire(thread_id, user_id=user_id)
    if sandbox_provider_sandbox_uses_thread_data_mounts(sandbox_provider, sandbox_id):
        _make_paths_readable(sync_paths)
        return SandboxSyncReceipt(sandbox=None)
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
    if await sandbox_provider_uses_thread_data_mounts_async(sandbox_provider):
        await run_upload_io_cancellation_safe(_make_paths_readable, sync_paths)
        return SandboxSyncReceipt(sandbox=None)

    sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=user_id)
    if sandbox_provider_sandbox_uses_thread_data_mounts(sandbox_provider, sandbox_id):
        await run_upload_io_cancellation_safe(_make_paths_readable, sync_paths)
        return SandboxSyncReceipt(sandbox=None)
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
        try:
            await rollback_sandbox_sync_async(receipt)
        except BaseException:
            logger.warning("Failed to roll back sandbox uploads after cancellation", exc_info=True)
        raise asyncio.CancelledError
    return receipt
