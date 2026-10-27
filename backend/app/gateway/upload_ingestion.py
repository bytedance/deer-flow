"""Shared thread-upload ingestion service (Projects Phase 2 Slice C, §7.3 item 3).

Owns the whole pipeline for files landing in a thread's uploads directory:
staging, ``claim_unique_filename``, size checks, optional conversion under
``uploads.auto_convert_documents``, sandbox-readable permissions, and
non-mounted-provider synchronization of original + derived files through the
authorized sandbox request lease. A denied ``sandbox:execute`` retains the
host upload without allocating a sandbox (ordinary uploads behavior);
acquisition, sync and conversion failures follow the ordinary upload error
and cleanup behavior.

Two callers share this pipeline:

- the ordinary uploads endpoint (``routers/uploads.py``), a thin adapter
  mapping ``UploadFile`` parts to chunk streams with zero behavior change;
- the project-shelf attach route (``routers/project_documents.py``), which
  feeds a staged shelf copy through the same lifecycle (§7.3 item 3).

Behavior-preservation bridge: the pre-extraction upload tests pin this
pipeline by patching collaborators on the ``routers.uploads`` module
namespace (``ensure_uploads_dir``, ``get_sandbox_provider``,
``_get_upload_limits``, ``_auto_convert_documents_enabled``,
``convert_file_to_markdown``, the low-level file machinery). The service
therefore resolves every collaborator through that module object at call
time (:func:`_uploads`) instead of importing the names directly, so those
patches keep binding to the one pipeline both callers use.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from deerflow.config.app_config import AppConfig
from deerflow.uploads.companions import register_companion, unregister_companion
from deerflow.utils.atomic_write import cleanup_failed_atomic_write
from deerflow.utils.file_io import await_drained, run_file_io

if TYPE_CHECKING:
    from fastapi import Request

    from app.gateway.authz import SandboxRequestLease
    from app.gateway.routers.uploads import UploadLimits

logger = logging.getLogger(__name__)


def _close_fd(fd: int | None) -> None:
    """Close a conversion-source descriptor, tolerating an already-closed one."""
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        with suppress(Exception):
            logger.warning("Failed to close upload conversion descriptor", exc_info=True)


def _close_abandoned_fd(duplication: asyncio.Future) -> None:
    """Close a descriptor whose owner was cancelled before it could take it."""
    if duplication.cancelled() or duplication.exception() is not None:
        return
    _close_fd(duplication.result())


async def _dup_for_conversion(fileno: int) -> int:
    """Duplicate *fileno* off-thread so cancellation cannot strand the copy.

    ``run_file_io`` cannot interrupt its worker: cancelling the await only
    abandons the result, and here that result is an open descriptor nothing
    would ever close — repeated cancellations would exhaust the Gateway's
    descriptor limit and pin the staged bytes of every unlinked upload. The
    duplication therefore runs as its own task, shielded from the caller's
    cancellation, and closes itself if the caller is gone by the time the
    worker finishes.
    """
    duplication = asyncio.ensure_future(run_file_io(os.dup, fileno))
    try:
        return await asyncio.shield(duplication)
    except BaseException:
        duplication.add_done_callback(_close_abandoned_fd)
        raise


def _copy_fd_to_path(fd: int, dest: Path) -> None:
    """Copy the bytes behind *fd* to *dest*, then close *fd*.

    Reads through the descriptor, not the name it was committed under, so the
    copy is the content this request wrote even if the name has since been
    replaced.
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        with open(dest, "wb") as out:
            while chunk := os.read(fd, 1 << 20):
                out.write(chunk)
    finally:
        _close_fd(fd)


def _uploads() -> Any:
    """Return the uploads router module (late binding — see module docstring)."""
    from app.gateway.routers import uploads

    return uploads


class UnsafeFilenameError(ValueError):
    """The display filename could not be normalized/claimed; ordinary behavior skips it."""


class UnsafeUploadDestinationError(Exception):
    """The claimed destination failed safety validation; carries the claimed name.

    Ordinary uploads record the file as skipped (``skipped_files``) and keep
    ingesting the rest of the request; attach maps it to an ingestion
    failure. Wraps the manager's ``UnsafeUploadPathError`` so the claimed
    (deduplicated) filename survives to the caller.
    """

    def __init__(self, filename: str) -> None:
        super().__init__(f"Unsafe upload destination: {filename}")
        self.filename = filename


class ThreadUploadIngestionService:
    """One thread's ingestion session: staging → conversion → permissions → sync.

    Lifecycle: :meth:`open` (uploads dir + existing-name seed + optional
    sandbox lease), one or
    more :meth:`ingest_chunks` calls, :meth:`finalize` (sandbox-readable
    permissions + non-mounted provider sync), then :meth:`aclose` (lease
    release) — use it as an async context manager. :meth:`cleanup_written`
    removes every file written by this session; the ordinary endpoint invokes
    it when a per-file failure aborts the request, and attach mirrors that.
    """

    def __init__(self, *, request: Request | None, thread_id: str, user_id: str, app_config: AppConfig) -> None:
        self._request = request
        self._thread_id = thread_id
        self._user_id = user_id
        self._config = app_config
        self._limits: UploadLimits | None = None
        self._uploads_dir: Path | None = None
        self._sync_to_sandbox = False
        self._sandbox_lease: SandboxRequestLease | None = None
        self._sandbox: Any = None
        self._auto_convert = False
        self._seen_filenames: set[str] = set()
        self._written_paths: list[Path] = []
        self._companion_pairs: list[tuple[Path, Path]] = []
        self._sync_targets: list[tuple[Path, str]] = []
        self._total_size = 0

    async def __aenter__(self) -> ThreadUploadIngestionService:
        try:
            await self.open()
        except BaseException:
            await self.aclose()
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    @property
    def limits(self) -> UploadLimits:
        assert self._limits is not None, "open() must run before limits is read"
        return self._limits

    async def open(self) -> None:
        """Resolve limits, ensure the uploads dir, seed existing names, acquire the lease.

        Mirrors the ordinary endpoint's setup order: a role denied
        ``sandbox:execute`` skips acquisition entirely (the host upload still
        succeeds); an allowed caller whose sandbox vanishes right after
        acquiring is a 500. ``ValueError`` from the uploads-dir resolution
        (unsafe thread id) propagates for the caller to map. The existing-name
        seed makes every later claim unique against the thread's CURRENT
        files, so no ingestion — ordinary upload or shelf attach — ever
        silently replaces a conversation file (same-name re-uploads land as
        ``name_1.ext``); the directory scan is offloaded per the filesystem
        convention.
        """
        uploads = _uploads()
        self._limits = uploads._get_upload_limits(self._config)
        self._uploads_dir = await run_file_io(uploads.ensure_uploads_dir, self._thread_id, user_id=self._user_id)
        listing = await run_file_io(uploads.list_files_in_dir, self._uploads_dir)
        self._seen_filenames.update(entry["filename"] for entry in listing["files"])
        sandbox_provider = uploads.get_sandbox_provider()
        self._sync_to_sandbox = not uploads._uses_thread_data_mounts(sandbox_provider)
        if self._sync_to_sandbox:

            async def acquire_lease() -> None:
                self._sandbox_lease = await uploads.try_acquire_sandbox_for_request(
                    self._request,
                    sandbox_provider,
                    self._thread_id,
                    user_id=self._user_id,
                    app_config=self._config,
                    owner_prefix="gateway:upload",
                    release_on_last=True,
                )
                self._sandbox = self._sandbox_lease.sandbox
                if not self._sandbox_lease.denied and self._sandbox is None:
                    raise HTTPException(status_code=500, detail="Failed to acquire sandbox")

            # Retain the returned holder even if acquisition's awaiter is gone.
            await await_drained(acquire_lease())
        self._auto_convert = uploads._auto_convert_documents_enabled(self._config)

    async def _link_commit_with_retry(self, uploads: Any, staged_path: Path, claimed_name: str) -> tuple[str, Path]:
        """Publish a staged file under *claimed_name*, atomically and with no overwrite.

        ``os.link`` (inside ``_commit_upload_temp_no_overwrite`` /
        ``_link_staged_no_overwrite``) fails with :class:`FileExistsError`
        when a concurrent session won the name after this session's seed —
        the next suffix is claimed against the seeded set and the link
        retried, so two concurrent ingestions of one name always land as
        ``name.ext`` + ``name_1.ext`` with both byte streams intact. The
        staged bytes stay hidden under the ``.upload-*.part`` pattern until
        the link makes the final name visible, fully formed.
        """
        assert self._uploads_dir is not None, "open() must run before committing destinations"

        async def publish() -> tuple[str, Path]:
            name = claimed_name
            while True:
                try:
                    path = await run_file_io(uploads._link_staged_no_overwrite, staged_path, self._uploads_dir, name)
                    self._written_paths.append(path)
                    return name, path
                except FileExistsError:
                    name = uploads.claim_unique_filename(name, self._seen_filenames)

        # Publication and recording its cleanup owner are one admitted step.
        return await await_drained(publish())

    async def ingest_chunks(self, chunks: AsyncIterator[bytes], *, display_name: str) -> dict[str, Any]:
        """Ingest a cancellable stream, reclaiming session files on cancellation.

        Only admitted filesystem steps and their ownership handoffs are drained;
        waiting for the next incoming chunk remains immediately cancellable.
        """
        try:
            return await self._ingest_chunks(chunks, display_name=display_name)
        except asyncio.CancelledError:
            try:
                await self.cleanup_written()
            except Exception:
                with suppress(Exception):
                    logger.warning("Failed to reclaim cancelled upload session files", exc_info=True)
            raise

    async def _ingest_chunks(self, chunks: AsyncIterator[bytes], *, display_name: str) -> dict[str, Any]:
        """Ingest one file from a chunk stream; return its wire metadata dict.

        Owns the per-file pipeline exactly as the ordinary endpoint defines
        it: normalize + claim a unique name, staged write with single-file
        and request-total size caps (413), an atomic no-overwrite link commit
        with next-suffix retry, and conversion with its companion-name claim
        when ``uploads.auto_convert_documents`` is on. Raises
        :class:`UnsafeFilenameError` (caller logs and skips),
        :class:`UnsafeUploadDestinationError` (caller records a skipped
        file), ``HTTPException`` (size/over-limit — caller cleans up and
        re-raises) or an unexpected error (caller cleans up and answers 500).
        """
        assert self._uploads_dir is not None and self._limits is not None, "open() must run before ingest_chunks()"
        uploads = _uploads()
        try:
            original_filename = uploads.normalize_filename(display_name)
        except ValueError as exc:
            raise UnsafeFilenameError(str(exc)) from exc
        safe_filename = uploads.claim_unique_filename(original_filename, self._seen_filenames)

        file_size = 0
        upload_temp = None
        convert_source_fd: int | None = None
        deferred_staged_path: Path | None = None

        async def prepare() -> None:
            nonlocal upload_temp
            upload_temp = await run_file_io(uploads._prepare_upload_destination, self._uploads_dir, safe_filename)

        async def publish() -> Path:
            nonlocal safe_filename, upload_temp, deferred_staged_path
            while True:
                try:
                    path = await run_file_io(
                        uploads._commit_upload_temp_no_overwrite,
                        upload_temp,
                        self._uploads_dir,
                        safe_filename,
                        unlink_staged=convert_source_fd is None,
                    )
                    break
                except FileExistsError:
                    safe_filename = uploads.claim_unique_filename(safe_filename, self._seen_filenames)
            self._written_paths.append(path)
            if convert_source_fd is not None:
                deferred_staged_path = upload_temp.temp_path
            upload_temp = None
            return path

        async def abort() -> None:
            nonlocal convert_source_fd
            _close_fd(convert_source_fd)
            convert_source_fd = None
            if upload_temp is not None:
                await run_file_io(uploads._abort_upload_temp, upload_temp)
            if deferred_staged_path is not None:
                await run_file_io(uploads._remove_staged_file, deferred_staged_path)

        try:
            await await_drained(prepare())
            async for chunk in chunks:
                file_size += len(chunk)
                self._total_size += len(chunk)
                if file_size > self._limits.max_file_size:
                    raise HTTPException(status_code=413, detail=f"File too large: {safe_filename}")
                if self._total_size > self._limits.max_total_size:
                    raise HTTPException(status_code=413, detail="Total upload size too large")
                await await_drained(run_file_io(uploads._write_upload_chunk, upload_temp, chunk))
            if self._auto_convert and Path(safe_filename).suffix.lower() in uploads.CONVERTIBLE_EXTENSIONS:
                # Conversion must read the bytes this request staged. Once the
                # name is committed a sandbox process can replace it with a
                # symlink, and converting by name would then pull a host file
                # into this thread's uploads. A descriptor on the staged inode
                # cannot be redirected that way.
                convert_source_fd = await _dup_for_conversion(upload_temp.handle.fileno())
            # Link-commit with collision retry: the FileExistsError arm
            # leaves the staged part in place for the retry under the next
            # suffix (the handle's second close is idempotent).
            #
            # The conversion descriptor above keeps the staged inode open, and
            # Windows refuses to remove a file that still has an open handle.
            # Publishing is therefore split from removing the staged name:
            # this request keeps ownership of the staged path and removes it
            # once the descriptor is released below.
            file_path = await await_drained(publish())
        except uploads.UnsafeUploadPathError as exc:
            await await_drained(abort())
            raise UnsafeUploadDestinationError(safe_filename) from exc
        except BaseException:
            # BaseException, not Exception: a cancellation between the
            # duplication and the commit would otherwise leave the descriptor
            # open, and nothing downstream owns it yet.
            await await_drained(abort())
            raise

        virtual_path = uploads.upload_virtual_path(safe_filename)
        if self._sync_to_sandbox:
            self._sync_targets.append((file_path, virtual_path))

        file_info: dict[str, Any] = {
            "filename": safe_filename,
            "size": file_size,
            "path": str(self._uploads_dir / safe_filename),
            "virtual_path": virtual_path,
            "artifact_url": uploads.upload_artifact_url(self._thread_id, safe_filename),
        }
        if safe_filename != original_filename:
            file_info["original_filename"] = original_filename
        logger.info(f"Saved file: {safe_filename} ({file_size} bytes) to {file_info['path']}")

        if convert_source_fd is not None:
            # The companion gets the same atomic no-overwrite commit as the
            # original: staged under the hidden .part pattern, link-committed
            # with next-suffix retry — conversion can never silently truncate
            # another uploaded or derived file, in this session or a
            # concurrent one.
            provisional_md_name = Path(safe_filename).with_suffix(".md").name
            unique_md_name = uploads.claim_unique_filename(provisional_md_name, self._seen_filenames)
            md_staging = self._uploads_dir / f"{uploads.UPLOAD_STAGING_PREFIX}{uuid.uuid4().hex}{uploads.UPLOAD_STAGING_SUFFIX}"
            # The staged bytes are copied out of the sandbox-writable tree and
            # converted there; the uploads dir only ever receives the result.
            # Creating that directory belongs inside the cleanup scope: it can
            # fail on its own (a full or unwritable temporary filesystem), and
            # the descriptor is already owned here — leaking it would also hold
            # the unlinked staged bytes until the process exits.
            private_dir: Path | None = None

            async def prepare_conversion() -> None:
                nonlocal private_dir
                private_dir = Path(await run_file_io(tempfile.mkdtemp, "-deerflow-convert"))

            def cleanup_conversion() -> None:
                # Release the pinned descriptor before removing either name
                # on Windows, and cover allocation/publication cancellations.
                cleanup_failed_atomic_write(md_staging, convert_source_fd)
                if deferred_staged_path is not None:
                    uploads._remove_staged_file(deferred_staged_path)
                if private_dir is not None:
                    shutil.rmtree(private_dir, ignore_errors=True)

            try:
                await await_drained(prepare_conversion())
                conversion_source = private_dir / safe_filename
                # Hand the descriptor over before the call: the copy closes it
                # even when it fails, so this scope must not close it again and
                # risk closing an unrelated descriptor that reused the number.
                # await_drained, not a bare await: a cancelled await would
                # cancel the queued executor job before its worker — and its
                # closing finally — ever ran, and draining also keeps the
                # worker from writing into a private directory this scope has
                # already removed.
                staged_fd, convert_source_fd = convert_source_fd, None
                await await_drained(run_file_io(_copy_fd_to_path, staged_fd, conversion_source))
                md_staged = await uploads.convert_file_to_markdown(conversion_source, output_path=md_staging)
                if not md_staged:
                    self._seen_filenames.discard(unique_md_name)
                else:
                    unique_md_name, md_path = await self._link_commit_with_retry(uploads, Path(md_staged), unique_md_name)
                    md_virtual_path = uploads.upload_virtual_path(md_path.name)
                    if self._sync_to_sandbox:
                        self._sync_targets.append((md_path, md_virtual_path))
                    file_info["markdown_file"] = md_path.name
                    self._companion_pairs.append((file_path, md_path))
                    file_info["markdown_path"] = str(self._uploads_dir / md_path.name)
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = uploads.upload_artifact_url(self._thread_id, md_path.name)
            except BaseException:
                self._seen_filenames.discard(unique_md_name)
                raise
            finally:
                await await_drained(run_file_io(cleanup_conversion))
        return file_info

    async def finalize(self) -> None:
        """Make written files sandbox-readable, then sync to a non-mounted sandbox.

        Runs after every file of the session ingested successfully — exactly
        the ordinary endpoint's tail. Failures here propagate (the host files
        stay in place; the caller does not clean them up, matching ordinary
        upload behavior for sync-phase errors).
        """
        await await_drained(self._finalize())

    async def _finalize(self) -> None:
        uploads = _uploads()
        # Uploaded files are created with 0o600 permissions (owner read/write
        # only). In Docker sandbox deployments the gateway writes as root but
        # the sandbox process runs as a non-root user (typically UID 1000).
        # Without group/other read bits the sandbox cannot access the files —
        # whether the uploads directory is bind-mounted into the container or
        # synced via sandbox.update_file. Always add group/other read bits so
        # every sandbox configuration can read the uploaded content.
        await run_file_io(uploads._make_uploaded_paths_sandbox_readable, self._written_paths)
        if self._sync_to_sandbox and self._sandbox is not None:
            for file_path, virtual_path in self._sync_targets:
                await run_file_io(uploads._sync_upload_to_sandbox, self._sandbox, file_path, virtual_path)
        # Record the final inode/version only after sandbox-readable chmod and
        # any synchronization have completed; chmod changes st_ctime_ns.
        for original, markdown in self._companion_pairs:
            await run_file_io(register_companion, original, markdown)

    async def cleanup_written(self) -> None:
        """Remove every file this session wrote (ordinary rejected-request cleanup)."""
        await await_drained(self._cleanup_written())

    async def _cleanup_written(self) -> None:
        if not self._written_paths:
            return
        uploads = _uploads()
        await run_file_io(uploads._cleanup_uploaded_paths, self._written_paths)
        for original, _ in self._companion_pairs:
            try:
                await run_file_io(unregister_companion, original)
            except Exception:
                with suppress(Exception):
                    logger.warning("Failed to remove upload companion record for %s", original, exc_info=True)
        self._companion_pairs = []
        self._written_paths = []

    async def aclose(self) -> None:
        """Release the sandbox request lease (failures are logged, never raised)."""
        if self._sandbox_lease is None:
            return
        try:
            await await_drained(self._sandbox_lease.release())
        except Exception:
            with suppress(Exception):
                logger.warning(
                    "Failed to release sandbox request lease after upload sync: %s",
                    self._sandbox_lease.sandbox_id,
                    exc_info=True,
                )
