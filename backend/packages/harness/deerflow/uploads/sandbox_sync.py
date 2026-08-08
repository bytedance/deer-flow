"""Provider-aware publication of authoritative upload paths to sandboxes."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deerflow.config.paths import get_paths
from deerflow.sandbox.sandbox_provider import (
    SandboxReconciliationIdentity,
    SandboxReconciliationResult,
    sandbox_provider_sandbox_uses_thread_data_mounts,
    sandbox_provider_uses_thread_data_mounts,
    sandbox_provider_uses_thread_data_mounts_async,
)
from deerflow.uploads.async_helpers import run_upload_io_cancellation_safe, wait_for_task_completion
from deerflow.uploads.layout import conversion_virtual_path
from deerflow.uploads.lease import UploadNameLease, UploadStageLease
from deerflow.uploads.manager import (
    _UPLOAD_DELETION_COMMIT_MARKER,
    _UPLOAD_DELETION_FINALIZE_GUARD,
    _UPLOAD_DELETION_PRIMARY_DIRNAME,
    RemoteDeletionCommitRequiredError,
    RemoteDeletionCompensatedError,
    _deletion_transaction_metadata,
    _normalize_existing_filename,
    _staged_deletion_remote_journal,
    _unlink_deletion_control_durably,
    cleanup_stale_upload_staging_files,
    make_upload_file_sandbox_readable,
    upload_virtual_path,
)

logger = logging.getLogger(__name__)
_REMOTE_DELETE_CONVERGENCE_ATTEMPTS = 3
_REMOTE_DELETE_JOURNAL_MAX_BYTES = 4096


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


def _fsync_parent_directory(path: Path) -> None:
    directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _write_all(descriptor: int, payload: bytes, *, error_message: str) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError(error_message)
        view = view[written:]


def _ensure_finalize_guard_durable(
    guard_path: Path,
    journal_data: dict[str, Any],
    journal_payload: bytes,
) -> None:
    try:
        descriptor = os.open(guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if _read_remote_delete_journal(guard_path) != journal_data:
            raise ValueError("remote deletion finalization guard does not match journal")
    else:
        try:
            _write_all(
                descriptor,
                journal_payload,
                error_message="Failed to write remote deletion finalization guard",
            )
            os.fsync(descriptor)
        except BaseException:
            try:
                os.close(descriptor)
            finally:
                try:
                    _unlink_deletion_control_durably(guard_path)
                except BaseException:
                    logger.error(
                        "Failed to remove an incomplete remote deletion finalization guard: %s",
                        guard_path,
                        exc_info=True,
                    )
            raise
        else:
            os.close(descriptor)
    # Existing guards may come from an attempt whose directory fsync failed.
    # Persist the reservation before making the journal unlink visible.
    _fsync_parent_directory(guard_path)


def _unlink_journal_durably(journal_path: Path) -> None:
    try:
        journal_data = _read_remote_delete_journal(journal_path)
    except FileNotFoundError:
        # A persistent finalization guard, when present, stays reserved until
        # startup cleanup durably confirms this observed journal absence.
        return
    filename = journal_data.get("filename")
    if not isinstance(filename, str):
        raise ValueError("remote deletion journal has no filename")
    journal_payload = json.dumps(
        journal_data,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    guard_path = journal_path.with_name(_UPLOAD_DELETION_FINALIZE_GUARD)
    _ensure_finalize_guard_durable(guard_path, journal_data, journal_payload)
    try:
        journal_path.unlink(missing_ok=True)
        _fsync_parent_directory(journal_path)
    except BaseException:
        # If unlink became visible but its directory fsync failed, allowing the
        # basename reservation to disappear would let a new generation reuse
        # the remote path before a crash resurrected the old journal. Recreate
        # the same journal entry when possible; the already-durable guard keeps
        # every process fail-closed even when recreation also fails.
        try:
            descriptor = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        except BaseException:
            logger.error("Failed to restore a remote deletion journal after durable unlink failed: %s", journal_path, exc_info=True)
        else:
            restored = False
            try:
                _write_all(
                    descriptor,
                    journal_payload,
                    error_message="Failed to restore remote deletion journal",
                )
                os.fsync(descriptor)
                restored = True
            except BaseException:
                logger.error("Failed to rewrite a remote deletion journal after durable unlink failed: %s", journal_path, exc_info=True)
            finally:
                os.close(descriptor)
            if restored:
                try:
                    _fsync_parent_directory(journal_path)
                except BaseException:
                    logger.error("Failed to persist a restored remote deletion journal directory entry: %s", journal_path, exc_info=True)
        raise
    _unlink_deletion_control_durably(guard_path)


def _read_remote_delete_journal(journal_path: Path) -> dict[str, Any]:
    path_stat = os.lstat(journal_path)
    if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
        raise ValueError("journal is not an exclusive regular file")
    descriptor = os.open(journal_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor_stat = os.fstat(descriptor)
        if not stat.S_ISREG(descriptor_stat.st_mode) or descriptor_stat.st_nlink != 1 or (descriptor_stat.st_dev, descriptor_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise ValueError("journal changed identity while opening")
        chunks: list[bytes] = []
        remaining = _REMOTE_DELETE_JOURNAL_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(payload) > _REMOTE_DELETE_JOURNAL_MAX_BYTES:
        raise ValueError("journal exceeds maximum size")
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("journal payload is not an object")
    return data


@dataclass(slots=True)
class _SandboxDeletionHook:
    sandbox: Any
    sandbox_id: str | None = None
    thread_id: str | None = None
    user_id: str | None = None
    provider_key: str | None = None
    backend_namespace: str | None = None
    incarnation_id: str | None = None
    _journal_path: Path | None = None
    _prepared_targets: tuple[tuple[str, bytes | None], ...] | None = None

    def _remove_journal(self) -> None:
        journal_path = self._journal_path
        if journal_path is None:
            return
        _unlink_journal_durably(journal_path)
        self._journal_path = None

    def prepare(
        self,
        filename: str,
        primary_path: Path,
        conversion_path: Path | None,
    ) -> None:
        """Persist enough context to retry an interrupted remote deletion."""
        if not self.sandbox_id or not self.thread_id or not self.provider_key or not self.backend_namespace or not self.incarnation_id:
            raise RuntimeError("Durable remote deletion requires provider, backend, sandbox, and incarnation identities")
        targets = (
            (upload_virtual_path(filename), primary_path.read_bytes()),
            (
                conversion_virtual_path(filename),
                conversion_path.read_bytes() if conversion_path is not None else None,
            ),
        )
        journal_path = _staged_deletion_remote_journal(primary_path)
        payload = json.dumps(
            {
                "version": 3,
                "sandbox_id": self.sandbox_id,
                "thread_id": self.thread_id,
                "user_id": self.user_id,
                "provider_key": self.provider_key,
                "backend_namespace": self.backend_namespace,
                "incarnation_id": self.incarnation_id,
                "filename": filename,
                "virtual_paths": [path for path, _bytes in targets],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        descriptor = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("Failed to write remote upload deletion journal")
                view = view[written:]
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            journal_path.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        try:
            directory_descriptor = os.open(journal_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except BaseException:
            journal_path.unlink(missing_ok=True)
            raise
        self._journal_path = journal_path
        self._prepared_targets = targets

    def abort_prepared(self) -> None:
        """Forget a journal when no remote side effect was allowed to start."""
        self._remove_journal()
        self._prepared_targets = None

    def _converge_to_deleted(self, virtual_paths: tuple[str, ...]) -> tuple[str, ...]:
        """Retry idempotent removal and return paths still not confirmed absent."""
        pending = list(dict.fromkeys(virtual_paths))
        for _attempt in range(_REMOTE_DELETE_CONVERGENCE_ATTEMPTS):
            still_pending: list[str] = []
            for virtual_path in pending:
                try:
                    self.sandbox.remove_file(virtual_path)
                except BaseException:
                    still_pending.append(virtual_path)
                    logger.warning(
                        "Failed to converge sandbox upload deletion: %s",
                        virtual_path,
                        exc_info=True,
                    )
            pending = still_pending
            if not pending:
                break
        return tuple(pending)

    def __call__(
        self,
        filename: str,
        primary_path: Path,
        conversion_path: Path | None,
    ) -> None:
        targets = self._prepared_targets
        if targets is None:
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
                self.sandbox.remove_file(virtual_path)
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
                        self.sandbox.update_file(rollback_path, rollback_bytes)
                    except BaseException:
                        compensation_failed = True
                        logger.warning(
                            "Failed to compensate partially deleted sandbox upload: %s",
                            rollback_path,
                            exc_info=True,
                        )
                if compensation_failed:
                    # Compensation is no longer an all-or-nothing rollback.
                    # Drive every target, including paths successfully written
                    # back above, to the deletion outcome before committing the
                    # authoritative host deletion. Repeated remove_file calls
                    # are idempotent and narrow transient transport failures.
                    pending = self._converge_to_deleted(tuple(path for path, _bytes in targets))
                    if not pending:
                        self._remove_journal()
                    detail = f"; unconfirmed remote paths: {pending!r}" if pending else ""
                    raise RemoteDeletionCommitRequiredError(f"Remote upload deletion could not be compensated{detail}") from delete_error
                raise RemoteDeletionCompensatedError(str(delete_error)) from delete_error
            removed.append((virtual_path, authoritative_bytes))
        self._remove_journal()


def _deletion_hook_for_sandbox(
    sandbox: Any,
    *,
    sandbox_id: str | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
    provider_key: str | None = None,
    backend_namespace: str | None = None,
    incarnation_id: str | None = None,
) -> _SandboxDeletionHook:
    return _SandboxDeletionHook(
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        thread_id=thread_id,
        user_id=user_id,
        provider_key=provider_key,
        backend_namespace=backend_namespace,
        incarnation_id=incarnation_id,
    )


def _declared_callable(instance: Any, name: str) -> Callable[..., Any] | None:
    """Return a real declared callable without trusting dynamic mock attributes."""
    try:
        inspect.getattr_static(instance, name)
    except AttributeError:
        return None
    candidate = getattr(instance, name, None)
    return candidate if callable(candidate) else None


def _sandbox_provider_reconciliation_key(sandbox_provider: Any) -> str:
    """Return the stable provider type key recorded by durable journals."""
    key_factory = _declared_callable(sandbox_provider, "reconciliation_provider_key")
    if key_factory is None:
        provider_type = type(sandbox_provider)
        key = f"{provider_type.__module__}.{provider_type.__qualname__}"
    else:
        key = key_factory()
    if not isinstance(key, str) or not key or len(key.encode("utf-8")) > 512:
        raise ValueError("Sandbox reconciliation provider key must be a non-empty string of at most 512 bytes")
    return key


def _prepare_sandbox_reconciliation_identity(
    sandbox_provider: Any,
    sandbox_id: str,
) -> SandboxReconciliationIdentity:
    identity_factory = _declared_callable(
        sandbox_provider,
        "prepare_sandbox_reconciliation_identity",
    )
    identity = identity_factory(sandbox_id) if identity_factory is not None else None
    if not isinstance(identity, SandboxReconciliationIdentity):
        raise RuntimeError("The active sandbox provider cannot establish a restart-safe backend and incarnation identity for upload deletion")
    if identity.provider_key != _sandbox_provider_reconciliation_key(sandbox_provider):
        raise ValueError("Sandbox reconciliation identity does not match its provider")
    for field in (
        identity.provider_key,
        identity.backend_namespace,
        identity.incarnation_id,
    ):
        if not isinstance(field, str) or not field or len(field.encode("utf-8")) > 512:
            raise ValueError("Sandbox reconciliation identity fields must be non-empty strings of at most 512 bytes")
    return identity


def _reconnect_sandbox_for_reconciliation(
    sandbox_provider: Any,
    sandbox_id: str,
    *,
    thread_id: str,
    user_id: str | None,
    identity: SandboxReconciliationIdentity,
) -> SandboxReconciliationResult:
    """Resolve one exact old sandbox without creating or redirecting it."""
    resolver = _declared_callable(sandbox_provider, "reconnect_sandbox_for_reconciliation")
    if resolver is not None:
        result = resolver(
            sandbox_id,
            thread_id=thread_id,
            user_id=user_id,
            identity=identity,
        )
    else:
        result = SandboxReconciliationResult.unknown()
    if not isinstance(result, SandboxReconciliationResult):
        raise TypeError("Sandbox reconciliation returned an invalid result")
    if result.status == "found" and result.sandbox is None:
        raise ValueError("Found sandbox reconciliation result has no sandbox")
    if result.status != "found" and (result.sandbox is not None or result.close_after):
        raise ValueError("Non-found sandbox reconciliation result owns no sandbox")
    return result


def _pending_remote_deletion_journals(base_dir: Path) -> list[Path]:
    patterns = (
        "threads/*/user-data/.upload-conversions/.upload-delete-*.part/.remote-delete.json",
        "users/*/threads/*/user-data/.upload-conversions/.upload-delete-*.part/.remote-delete.json",
    )
    journals: list[Path] = []
    for pattern in patterns:
        for path in base_dir.glob(pattern):
            try:
                primary_dir_stat = os.lstat(path.parent / _UPLOAD_DELETION_PRIMARY_DIRNAME)
                commit_stat = os.lstat(path.parent / _UPLOAD_DELETION_COMMIT_MARKER)
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(primary_dir_stat.st_mode) and not stat.S_ISLNK(primary_dir_stat.st_mode) and stat.S_ISREG(commit_stat.st_mode) and commit_stat.st_nlink == 1:
                journals.append(path)
    return sorted(journals)


def _validate_remote_delete_tombstone(journal_path: Path, filename: str) -> Path:
    """Validate that a journal still names its retained host generation."""
    transaction_dir = journal_path.parent
    metadata = _deletion_transaction_metadata(transaction_dir.name)
    if metadata is None:
        raise ValueError("invalid remote deletion transaction name")
    expected_inode, _recover_on_crash = metadata
    primary_dir = transaction_dir / _UPLOAD_DELETION_PRIMARY_DIRNAME
    primary_dir_stat = os.lstat(primary_dir)
    if stat.S_ISLNK(primary_dir_stat.st_mode) or not stat.S_ISDIR(primary_dir_stat.st_mode):
        raise ValueError("invalid remote deletion primary directory")
    with os.scandir(primary_dir) as entries:
        primary_entries = list(entries)
    if len(primary_entries) != 1:
        raise ValueError("remote deletion transaction must retain one primary")
    primary_entry = primary_entries[0]
    primary_stat = primary_entry.stat(follow_symlinks=False)
    if primary_entry.name != filename or not stat.S_ISREG(primary_stat.st_mode) or primary_stat.st_nlink != 1 or primary_stat.st_ino != expected_inode:
        raise ValueError("remote deletion journal does not match its primary generation")
    return transaction_dir.parent.parent / "uploads"


def reconcile_pending_remote_deletions(
    *,
    sandbox_provider_factory: Callable[[], Any],
    base_dir: Path | str | None = None,
) -> int:
    """Retry durable remote upload deletions before host transaction cleanup."""
    root = Path(base_dir) if base_dir is not None else get_paths().base_dir
    journals = _pending_remote_deletion_journals(root)
    if not journals:
        return 0
    sandbox_provider: Any | None = None
    reconciled = 0
    for journal_path in journals:
        transaction_dir = journal_path.parent
        stage_lease = UploadStageLease.try_acquire(transaction_dir.parent, transaction_dir.name)
        if stage_lease is None:
            continue
        try:
            try:
                data = _read_remote_delete_journal(journal_path)
                if data.get("version") != 3:
                    raise ValueError("unsupported journal version")
                filename = data.get("filename")
                thread_id = data.get("thread_id")
                user_id = data.get("user_id")
                sandbox_id = data.get("sandbox_id")
                provider_key = data.get("provider_key")
                backend_namespace = data.get("backend_namespace")
                incarnation_id = data.get("incarnation_id")
                virtual_paths = data.get("virtual_paths")
                expected_paths = [
                    upload_virtual_path(filename) if isinstance(filename, str) else None,
                    conversion_virtual_path(filename) if isinstance(filename, str) else None,
                ]
                if (
                    not isinstance(filename, str)
                    or not isinstance(thread_id, str)
                    or not thread_id
                    or (user_id is not None and not isinstance(user_id, str))
                    or not isinstance(sandbox_id, str)
                    or not sandbox_id
                    or not isinstance(provider_key, str)
                    or not provider_key
                    or len(provider_key.encode("utf-8")) > 512
                    or not isinstance(backend_namespace, str)
                    or not backend_namespace
                    or len(backend_namespace.encode("utf-8")) > 512
                    or not isinstance(incarnation_id, str)
                    or not incarnation_id
                    or len(incarnation_id.encode("utf-8")) > 512
                    or virtual_paths != expected_paths
                ):
                    raise ValueError("invalid remote deletion journal fields")
                if _normalize_existing_filename(filename) != filename:
                    raise ValueError("invalid remote deletion journal filename")
                uploads_dir = _validate_remote_delete_tombstone(journal_path, filename)

                if sandbox_provider is None:
                    sandbox_provider = sandbox_provider_factory()
                if _sandbox_provider_reconciliation_key(sandbox_provider) != provider_key:
                    logger.warning(
                        "Pending remote upload deletion belongs to provider namespace %r, not the active namespace; leaving journal pending",
                        provider_key,
                    )
                    continue
                identity = SandboxReconciliationIdentity(
                    provider_key=provider_key,
                    backend_namespace=backend_namespace,
                    incarnation_id=incarnation_id,
                )
                name_lease = UploadNameLease.try_acquire(
                    uploads_dir,
                    filename,
                    allow_legacy_posix_filename=True,
                )
                if name_lease is None:
                    continue
                try:
                    result = _reconnect_sandbox_for_reconciliation(
                        sandbox_provider,
                        sandbox_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        identity=identity,
                    )
                    if result.status == "unknown":
                        logger.warning(
                            "Exact sandbox %r could not be resolved for pending remote upload deletion; leaving journal pending",
                            sandbox_id,
                        )
                        continue
                    if result.status == "absent":
                        _unlink_journal_durably(journal_path)
                        reconciled += 1
                        continue
                    sandbox = result.sandbox
                    try:
                        pending = _SandboxDeletionHook(sandbox)._converge_to_deleted(tuple(virtual_paths))
                        if pending:
                            logger.warning(
                                "Remote upload deletion remains pending for %s: %s",
                                journal_path,
                                pending,
                            )
                            continue
                        _unlink_journal_durably(journal_path)
                        reconciled += 1
                    finally:
                        if result.close_after:
                            try:
                                sandbox.close()
                            except BaseException:
                                logger.warning("Failed to close a transient reconciliation sandbox client", exc_info=True)
                finally:
                    name_lease.release()
            except BaseException:
                logger.warning(
                    "Failed to reconcile remote upload deletion journal: %s",
                    journal_path,
                    exc_info=True,
                )
        finally:
            stage_lease.release()
    return reconciled


def prepare_upload_deletion(
    sandbox_provider: Any,
    thread_id: str,
    *,
    user_id: str | None,
) -> Callable[[str, Path, Path | None], None] | None:
    """Return a lease-safe remote deletion hook for an explicitly synced sandbox."""
    reconcile_pending_remote_deletions(sandbox_provider_factory=lambda: sandbox_provider)
    # Guard-only transactions are intentionally absent from journal replay.
    # Always run ordinary cleanup so it can fsync-confirm the journal absence
    # and release a finalization guard without waiting for a process restart.
    cleanup_stale_upload_staging_files()
    if sandbox_provider_uses_thread_data_mounts(sandbox_provider):
        return None
    sandbox_id = sandbox_provider.acquire(thread_id, user_id=user_id)
    if sandbox_provider_sandbox_uses_thread_data_mounts(sandbox_provider, sandbox_id):
        return None
    sandbox = sandbox_provider.get(sandbox_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {sandbox_id!r} not found after acquire")
    identity = _prepare_sandbox_reconciliation_identity(
        sandbox_provider,
        sandbox_id,
    )
    return _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id=sandbox_id,
        thread_id=thread_id,
        user_id=user_id,
        provider_key=identity.provider_key,
        backend_namespace=identity.backend_namespace,
        incarnation_id=identity.incarnation_id,
    )


async def prepare_upload_deletion_async(
    sandbox_provider: Any,
    thread_id: str,
    *,
    user_id: str | None,
) -> Callable[[str, Path, Path | None], None] | None:
    """Async counterpart that keeps remote acquisition off the event loop."""
    await asyncio.to_thread(
        reconcile_pending_remote_deletions,
        sandbox_provider_factory=lambda: sandbox_provider,
    )
    await asyncio.to_thread(cleanup_stale_upload_staging_files)
    if await sandbox_provider_uses_thread_data_mounts_async(sandbox_provider):
        return None
    sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=user_id)
    if sandbox_provider_sandbox_uses_thread_data_mounts(sandbox_provider, sandbox_id):
        return None
    sandbox = sandbox_provider.get(sandbox_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {sandbox_id!r} not found after acquire")
    identity = await asyncio.to_thread(
        _prepare_sandbox_reconciliation_identity,
        sandbox_provider,
        sandbox_id,
    )
    return _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id=sandbox_id,
        thread_id=thread_id,
        user_id=user_id,
        provider_key=identity.provider_key,
        backend_namespace=identity.backend_namespace,
        incarnation_id=identity.incarnation_id,
    )


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
