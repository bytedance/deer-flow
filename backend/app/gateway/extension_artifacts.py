"""Bounded output capture without symlink traversal or mutable-path rereads."""

import os
import stat

from deerflow_extension_api import AgentRunError

from app.gateway.path_utils import normalize_outputs_virtual_path
from deerflow.config.paths import get_paths

MAX_BYTES = 2 * 1024 * 1024


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
