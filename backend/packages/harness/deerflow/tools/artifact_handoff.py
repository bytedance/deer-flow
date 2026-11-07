"""Verified artifact handoff between conversations belonging to one user."""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Annotated

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime
from deerflow.utils.thread_id import validate_thread_id

MAX_BYTES = 2 * 1024 * 1024
_OUTPUTS_PREFIX = "mnt/user-data/outputs/"


def _normalized_relative_path(virtual_path: str) -> PurePosixPath:
    if not isinstance(virtual_path, str) or "\\" in virtual_path or any(ord(char) < 32 for char in virtual_path):
        raise ValueError("Invalid shared artifact path")
    normalized = posixpath.normpath(virtual_path.lstrip("/")).lstrip("/")
    if not normalized.startswith(_OUTPUTS_PREFIX) or normalized == _OUTPUTS_PREFIX.rstrip("/"):
        raise ValueError("Shared artifact must stay inside /mnt/user-data/outputs")
    relative = PurePosixPath(normalized.removeprefix(_OUTPUTS_PREFIX))
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("Invalid shared artifact path")
    return relative


def _open_directory(root: str, parts: tuple[str, ...], *, create: bool = False) -> int:
    if os.name != "posix":
        raise ValueError("Shared artifact handoff requires POSIX")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=directory)
                except FileExistsError:
                    pass
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        return directory
    except Exception:
        os.close(directory)
        raise


def _open_outputs_directory(root: str, parts: tuple[str, ...], *, create: bool = False) -> int:
    paths = get_paths()
    try:
        root_parts = Path(root).relative_to(paths.base_dir).parts
    except ValueError:
        raise ValueError("Shared artifact output root escapes the runtime home") from None
    return _open_directory(str(paths.base_dir), (*root_parts, *parts), create=create)


def _read_host_output_snapshot(user_id: str, origin_thread_id: str, virtual_path: str) -> bytes:
    validate_thread_id(origin_thread_id)
    relative = _normalized_relative_path(virtual_path)
    root = get_paths().sandbox_outputs_dir(origin_thread_id, user_id=user_id)
    directory = _open_outputs_directory(root, relative.parts[:-1])
    try:
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                raise ValueError("Shared artifact must be a regular file of at most 2 MiB")
            content = source.read(MAX_BYTES + 1)
            after = os.fstat(source.fileno())
            if len(content) > MAX_BYTES or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Shared artifact changed during capture")
            return content
    finally:
        os.close(directory)


def _publish_host_output(user_id: str, runtime: Runtime, origin_thread_id: str, virtual_path: str, expected_sha256: str) -> dict[str, str]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("Expected a lowercase SHA-256 digest")
    content = _read_host_output_snapshot(user_id, origin_thread_id, virtual_path)
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("Source artifact changed; expected SHA-256 does not match")

    relative = _normalized_relative_path(virtual_path)
    outputs_path = (runtime.state or {}).get("thread_data", {}).get("outputs_path")
    context = getattr(runtime, "context", None)
    thread_id = context.get("thread_id") if isinstance(context, dict) else None
    if not outputs_path or not isinstance(thread_id, str) or not thread_id:
        raise ValueError("Destination outputs directory is unavailable")
    expected_outputs_path = get_paths().sandbox_outputs_dir(thread_id, user_id=user_id)
    if os.path.abspath(outputs_path) != os.path.abspath(expected_outputs_path):
        raise ValueError("Destination outputs directory does not belong to the current thread")
    directory = _open_outputs_directory(outputs_path, relative.parts[:-1], create=True)
    temporary = f".shared-{uuid.uuid4().hex}.part"
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        created = True
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        import fcntl

        fcntl.flock(directory, fcntl.LOCK_EX)
        try:
            try:
                os.link(temporary, relative.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                pass
            os.unlink(temporary, dir_fd=directory)
            created = False
            descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(descriptor, "rb") as published:
                before = os.fstat(published.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != len(content):
                    raise ValueError("Destination artifact changed; existing file retained")
                published_content = published.read(MAX_BYTES + 1)
                after = os.fstat(published.fileno())
                if published_content != content or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError("Destination artifact changed; existing file retained")
            return {
                "path": f"/mnt/user-data/outputs/{relative.as_posix()}",
                "sha256": actual_sha256,
                "origin_thread_id": origin_thread_id,
            }
        finally:
            fcntl.flock(directory, fcntl.LOCK_UN)
    finally:
        try:
            if created:
                os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


@tool("present_shared_artifact", parse_docstring=True)
def present_shared_artifact(
    runtime: Runtime,
    origin_thread_id: str,
    path: str,
    sha256: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Publish an artifact from another conversation after verifying its exact source bytes.

    Args:
        origin_thread_id: The source conversation that owns the artifact.
        path: The source /mnt/user-data/outputs path, including any subdirectories.
        sha256: The expected lowercase SHA-256 of the source bytes.
    """
    try:
        result = _publish_host_output(resolve_runtime_user_id(runtime), runtime, origin_thread_id, path, sha256)
        message = f"Successfully presented shared artifact; origin_thread_id={origin_thread_id}; sha256={result['sha256']}"
        return Command(update={"artifacts": [result["path"]], "messages": [ToolMessage(message, tool_call_id=tool_call_id)]})
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: {exc}", tool_call_id=tool_call_id)]})
