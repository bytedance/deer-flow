"""Bounded output capture without symlink traversal or mutable-path rereads."""

import hashlib
import logging
import os
import re
import stat
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from deerflow_extension_api import AgentRunError
from fastapi import Request

from app.gateway.authz import try_acquire_sandbox_for_request
from app.gateway.path_utils import normalize_outputs_virtual_path
from deerflow.config.paths import get_paths
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import get_sandbox_provider

MAX_BYTES = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


def validate_import_receipts(values: object) -> None:
    """Reject malformed receipts or more than four bounded imports with 422."""
    if not isinstance(values, list) or len(values) > 4:
        raise AgentRunError(422, "Choose at most four imported artifacts")
    for value in values:
        if not isinstance(value, dict) or set(value) != {"filename", "path", "sha256", "size"}:
            raise AgentRunError(422, "Invalid artifact import receipt")
        filename = value["filename"]
        if not isinstance(filename, str) or not filename or filename in (".", "..") or any(c in filename for c in "/\\") or any(ord(c) < 32 for c in filename):
            raise AgentRunError(422, "Invalid artifact import filename")
        try:
            valid = len(filename.encode()) <= 255
        except UnicodeError:
            valid = False
        if (
            not valid
            or value["path"] != "/mnt/user-data/uploads/" + filename
            or not isinstance(value["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
            or type(value["size"]) is not int
            or not 0 <= value["size"] <= MAX_BYTES
        ):
            raise AgentRunError(422, "Invalid artifact import receipt")


@asynccontextmanager
async def snapshot_sandbox(request: Request, user_id: str, thread_id: str) -> AsyncIterator[Sandbox | None]:
    """Yield a remote sandbox lease, or None for host-mounted thread data.

    Permission denial raises 403 and an unavailable sandbox raises 503. Release
    drains on cancellation; exact snapshots never fall back after a denied lease.
    """
    from app.gateway.routers.uploads import _uses_thread_data_mounts
    from deerflow.config.app_config import get_app_config
    from deerflow.utils.file_io import await_drained, run_file_io

    provider = get_sandbox_provider()
    lease = None
    try:
        if not _uses_thread_data_mounts(provider):
            lease = await try_acquire_sandbox_for_request(request, provider, thread_id, user_id=user_id, app_config=await run_file_io(get_app_config), owner_prefix="gateway:artifact-snapshot", release_on_last=True)
            if lease.denied:
                raise AgentRunError(403, "Sandbox permission denied for artifact snapshots")
            if lease.sandbox is None:
                raise AgentRunError(503, "Sandbox unavailable for artifact snapshots")
        yield lease.sandbox if lease is not None else None
    finally:
        if lease is not None:
            await await_drained(lease.release())


async def validate_capture_support(request: Request, user_id: str, thread_id: str) -> None:
    """Require POSIX capture and probe remote support before registration.

    Raise 422 for unsupported capture, retaining lease authorization failures.
    """
    from deerflow.sandbox.artifact_snapshot import validate_snapshot_support
    from deerflow.utils.file_io import run_file_io

    if os.name != "posix":
        raise AgentRunError(422, "Artifact capture requires POSIX")
    async with snapshot_sandbox(request, user_id, thread_id) as sandbox:
        if sandbox is not None:
            await run_file_io(validate_snapshot_support, sandbox)


def validate_import(filename: object, content: object) -> None:
    """Reject unsafe filenames, non-POSIX hosts or content over 2 MiB with 422."""
    if os.name != "posix" or not isinstance(filename, str) or not filename or filename in (".", "..") or any(c in filename for c in "/\\") or any(ord(c) < 32 for c in filename):
        raise AgentRunError(422, "Use a plain artifact filename on POSIX")
    try:
        valid = len(filename.encode()) <= 160
    except UnicodeError:
        valid = False
    if not valid or not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise AgentRunError(422, "Artifact filename is too long or content exceeds 2 MiB")


def write_import_snapshot(user_id: str, thread_id: str, namespace: str, filename: str, content: bytes) -> dict[str, Any]:
    """Publish a confined content-addressed upload and return its import receipt.

    Reuse only identical regular files; retain existing edits and raise 422 for
    unsafe or changed destinations. Run filesystem work off the event loop.
    """
    validate_import(filename, content)
    digest = hashlib.sha256(content).hexdigest()
    identity = hashlib.sha256(namespace.encode() + b"\0" + filename.encode() + b"\0" + content).hexdigest()[:32]
    destination = f"artifact-{identity}-{filename}"
    paths = get_paths()
    root = paths.base_dir.resolve()
    relative = paths.sandbox_uploads_dir(thread_id, user_id=user_id).relative_to(paths.base_dir)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    temporary = ".upload-" + uuid.uuid4().hex + ".part"
    created = False
    try:
        for part in relative.parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=directory)
            except FileExistsError:
                pass
            next_dir = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_dir
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        created = True
        with os.fdopen(fd, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
            os.fchmod(target.fileno(), 0o644)
        try:
            os.link(temporary, destination, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            pass
        os.unlink(temporary, dir_fd=directory)
        created = False
        fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as existing:
            before = os.fstat(existing.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != len(content):
                raise AgentRunError(422, "Imported artifact was changed; existing file retained")
            data = existing.read(MAX_BYTES + 1)
            after = os.fstat(existing.fileno())
            if data != content or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise AgentRunError(422, "Imported artifact was changed; existing file retained")
        return {"filename": destination, "path": "/mnt/user-data/uploads/" + destination, "sha256": digest, "size": len(content)}
    except OSError as exc:
        raise AgentRunError(422, "Artifact import destination unavailable or unsafe") from exc
    finally:
        try:
            if created:
                os.unlink(temporary, dir_fd=directory)
        except OSError:
            logger.warning("Failed to clean up an abandoned artifact import staging file", exc_info=True)
        finally:
            os.close(directory)


async def import_snapshot(request: Request, user_id: str, thread_id: str, namespace: str, filename: str, content: bytes) -> dict[str, Any]:
    """Return a receipt after publishing identical host and remote uploads.

    Retain existing edits; unsafe/changed snapshots raise 422 and lease failures
    keep their authorization/availability status. Cancellation drains file I/O.
    """
    from deerflow.sandbox.artifact_snapshot import publish_snapshot
    from deerflow.utils.file_io import run_file_io

    validate_import(filename, content)
    async with snapshot_sandbox(request, user_id, thread_id) as sandbox:
        result = await run_file_io(write_import_snapshot, user_id, thread_id, namespace, filename, content)
        if sandbox is not None:
            await run_file_io(publish_snapshot, sandbox, result["filename"], content)
        return result


async def read_snapshot(request: Request, user_id: str, thread_id: str, path: str, *, max_bytes: int = MAX_BYTES) -> bytes:
    """Capture bounded output bytes through host storage or an authorized lease.

    Non-output paths raise HTTP 400; unsafe files raise 422 and host mutation
    during capture raises 409. Remote snapshot and lease errors retain their
    status. Cancellation drains I/O.
    """
    from deerflow.sandbox.artifact_snapshot import read_snapshot as read_remote
    from deerflow.utils.file_io import run_file_io

    path = normalize_outputs_virtual_path(path)
    async with snapshot_sandbox(request, user_id, thread_id) as sandbox:
        if sandbox is not None:
            return await run_file_io(read_remote, sandbox, path.removeprefix("/mnt/user-data/outputs/"), max_bytes=max_bytes)
        return await run_file_io(read_output_snapshot, user_id, thread_id, path, max_bytes=max_bytes)


async def verify_imports(request: Request, user_id: str, thread_id: str, receipts: list[dict[str, Any]], *, lifetime: AsyncExitStack | None = None) -> None:
    """Verify receipt bytes after new admission and before Agent construction.

    A supplied lifetime retains the remote lease through execution; otherwise it
    ends here. Missing, changed or inaccessible copies raise an artifact-specific
    422. Cancellation drains file I/O before the enclosing lease is released.
    """
    from deerflow.sandbox.artifact_snapshot import verify_snapshot
    from deerflow.utils.file_io import run_file_io

    try:
        async with AsyncExitStack() as temporary:
            # A run retains its remote client through execution: releasing it
            # after preflight could let the provider recycle the verified VM.
            sandbox = await (lifetime or temporary).enter_async_context(snapshot_sandbox(request, user_id, thread_id))
            for receipt in receipts:
                data = await run_file_io(_read_host_snapshot, user_id, thread_id, receipt["filename"], "uploads")
                if len(data) != receipt["size"] or hashlib.sha256(data).hexdigest() != receipt["sha256"]:
                    raise AgentRunError(422, "Imported copy changed")
                if sandbox is not None:
                    await run_file_io(verify_snapshot, sandbox, receipt["filename"], receipt["sha256"], receipt["size"])
    except (AgentRunError, OSError) as exc:
        raise AgentRunError(422, "Attached artifact copy is unavailable or changed; inspect the team artifacts and send a new request") from exc


def read_output_snapshot(user_id: str, thread_id: str, path: str, *, max_bytes: int = MAX_BYTES) -> bytes:
    """Read bounded host output bytes without following links.

    Non-output paths raise HTTP 400; unsafe files raise 422 and mutation during
    capture raises 409. Run filesystem work off the event loop.
    """
    if os.name != "posix" or not isinstance(path, str):
        raise AgentRunError(422, "Output capture requires POSIX and an output path")
    path = normalize_outputs_virtual_path(path)
    return _read_host_snapshot(user_id, thread_id, path.removeprefix("/mnt/user-data/outputs/"), "outputs", max_bytes=max_bytes)


def _read_host_snapshot(user_id: str, thread_id: str, path: str, area: str, *, max_bytes: int = MAX_BYTES) -> bytes:
    paths = get_paths()
    root = paths.base_dir.resolve()
    base = paths.sandbox_outputs_dir(thread_id, user_id=user_id) if area == "outputs" else paths.sandbox_uploads_dir(thread_id, user_id=user_id)
    relative = base.relative_to(paths.base_dir)
    parts = (*relative.parts, *path.split("/"))
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            next_dir = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_dir
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes or before.st_nlink != 1:
                raise AgentRunError(422, "Artifact must be a regular, unlinked file within the capture limit")
            content = source.read(max_bytes + 1)
            after = os.fstat(source.fileno())
            if len(content) > max_bytes or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise AgentRunError(409, "Artifact changed during capture")
            return content
    except OSError as exc:
        raise AgentRunError(422, "Artifact unavailable or unsafe") from exc
    finally:
        os.close(directory)
