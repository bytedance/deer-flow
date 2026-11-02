"""Bounded output capture without symlink traversal or mutable-path rereads."""

import hashlib
import logging
import os
import stat
import uuid

from deerflow_extension_api import AgentRunError

from app.gateway.authz import try_acquire_sandbox_for_request
from app.gateway.path_utils import normalize_outputs_virtual_path
from deerflow.config.paths import get_paths
from deerflow.sandbox.sandbox_provider import get_sandbox_provider

MAX_BYTES = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


def validate_import(filename, content):
    if os.name != "posix" or not isinstance(filename, str) or not filename or filename in (".", "..") or any(c in filename for c in "/\\") or any(ord(c) < 32 for c in filename):
        raise AgentRunError(422, "Use a plain artifact filename on POSIX")
    try:
        valid = len(filename.encode()) <= 160
    except UnicodeError:
        valid = False
    if not valid or not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise AgentRunError(422, "Artifact filename is too long or content exceeds 2 MiB")


def write_import_snapshot(user_id, thread_id, namespace, filename, content):
    """Publish a content-addressed upload without replacing existing files."""
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


async def import_snapshot(request, user_id, thread_id, namespace, filename, content):
    """Publish on the host and synchronize the exact bytes to remote sandboxes."""
    from app.gateway.routers.uploads import _uses_thread_data_mounts
    from deerflow.config.app_config import get_app_config
    from deerflow.utils.file_io import await_drained, run_file_io

    validate_import(filename, content)
    provider = get_sandbox_provider()
    lease = None
    try:
        if not _uses_thread_data_mounts(provider):
            lease = await try_acquire_sandbox_for_request(request, provider, thread_id, user_id=user_id, app_config=await run_file_io(get_app_config), owner_prefix="gateway:artifact-import", release_on_last=True)
            if lease.denied:
                raise AgentRunError(403, "Sandbox permission denied for artifact import")
            if lease.sandbox is None:
                raise AgentRunError(503, "Sandbox unavailable for artifact import")
        result = await run_file_io(write_import_snapshot, user_id, thread_id, namespace, filename, content)
        if lease is not None:
            await run_file_io(lease.sandbox.update_file, result["path"], content)
        return result
    finally:
        if lease is not None:
            await await_drained(lease.release())


def read_output_snapshot(user_id, thread_id, path):
    if os.name != "posix" or not isinstance(path, str):
        raise AgentRunError(422, "Output capture requires POSIX and an output path")
    path = normalize_outputs_virtual_path(path)
    paths = get_paths()
    root = paths.base_dir.resolve()
    relative = paths.sandbox_outputs_dir(thread_id, user_id=user_id).relative_to(paths.base_dir)
    parts = (*relative.parts, *path.removeprefix("/mnt/user-data/outputs/").split("/"))
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            next_dir = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_dir
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                raise AgentRunError(422, "Artifact must be a regular file of at most 2 MiB")
            content = source.read(MAX_BYTES + 1)
            after = os.fstat(source.fileno())
            if len(content) > MAX_BYTES or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise AgentRunError(409, "Artifact changed during capture")
            return content
    except OSError as exc:
        raise AgentRunError(422, "Artifact unavailable or unsafe") from exc
    finally:
        os.close(directory)
