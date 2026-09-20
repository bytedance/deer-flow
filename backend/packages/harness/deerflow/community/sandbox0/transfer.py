"""Bounded file transfer between guest workspaces and DeerFlow's host views."""

from __future__ import annotations

import io
import os
import shlex
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath

MAX_FILES = 2000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024

# Execute fixed scripts via argv, never interpolate a filename into Python code.
_UPLOAD = r"""
import os, pathlib, shutil, sys, zipfile
root = pathlib.Path('/mnt/skills')
if os.path.realpath('/mnt') != '/mnt' or root.is_symlink():
    raise RuntimeError('skills root must not be a symlink')
with zipfile.ZipFile(sys.argv[1]) as archive:
    for member in archive.infolist():
        path = pathlib.PurePosixPath(member.filename)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in ('public','custom','legacy','integrations'):
            raise RuntimeError('invalid skill archive member')
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()
    archive.extractall(root)
for category in ('public','custom','legacy','integrations'):
    (root/category).mkdir(exist_ok=True)
"""

_DOWNLOAD = r"""
import os, pathlib, sys, zipfile
root = pathlib.Path('/mnt/user-data')
if os.path.realpath(root) != str(root):
    raise RuntimeError('user-data root must not be a symlink')
count = total = 0
with zipfile.ZipFile(sys.argv[1], 'w', compression=zipfile.ZIP_STORED) as archive:
    for category in ('workspace', 'outputs'):
        base = root/category
        if base.is_symlink():
            raise RuntimeError('artifact category must not be a symlink')
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if not (pathlib.Path(directory)/d).is_symlink()]
            for name in files:
                path = pathlib.Path(directory)/name
                if path.is_symlink() or not path.is_file():
                    continue
                size = path.stat().st_size
                count += 1
                total += size
                if count > 2000 or size > 20*1024*1024 or total > 100*1024*1024:
                    raise RuntimeError('artifact transfer limit exceeded; workspace remains in Sandbox0')
                archive.write(path, str(path.relative_to(root)))
"""


def _remote_script(sandbox, source: str, remote_path: str):
    sandbox._checked(f"python3 -c {shlex.quote(source)} {shlex.quote(remote_path)}", timeout=120)


def upload_skills(sandbox, projection):
    """Replace all four managed categories; never trust guest signature files."""
    data = io.BytesIO()
    count = total = 0
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for category in ("public", "custom", "legacy", "integrations"):
            root = getattr(projection, category).resolve()
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    raise PermissionError("skill symlink escapes its projection")
                if not resolved.is_file():
                    continue
                size = resolved.stat().st_size
                count += 1
                total += size
                if count > MAX_FILES or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise OSError("skill transfer limit exceeded")
                archive.writestr(f"{category}/{path.relative_to(root).as_posix()}", resolved.read_bytes())
    remote_path = f"/tmp/deerflow-skills-{uuid.uuid4().hex}.zip"
    try:
        sandbox.update_file(remote_path, data.getvalue())
        _remote_script(sandbox, _UPLOAD, remote_path)
    finally:
        sandbox.remote.delete_file(remote_path)


def _write_host_file(root: Path, name: str, data: bytes):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] not in {"workspace", "outputs"}:
        raise PermissionError("artifact path escapes the thread workspace")
    # Do not follow links left by a previous local provider into host files.
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise PermissionError("artifact destination is a symlink")
    destination = root.joinpath(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".sandbox0-{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def download_artifacts(sandbox, root: Path):
    """Mirror workspace/output files for the existing artifact HTTP endpoints.

    This is a bounded presentation copy, not the durable source of truth. Files
    removed in the guest are not pruned from the host. A failure is surfaced
    while the provider still checkpoints the remote workspace.
    """
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise PermissionError("artifact root contains a symlink")
    remote_path = f"/tmp/deerflow-artifacts-{uuid.uuid4().hex}.zip"
    try:
        _remote_script(sandbox, _DOWNLOAD, remote_path)
        data = sandbox.remote.read_file(remote_path)
        if len(data) > MAX_TOTAL_BYTES + 2 * 1024 * 1024:
            raise OSError("artifact archive exceeds transfer limit")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_TOTAL_BYTES:
                raise OSError("artifact archive exceeds transfer limit")
            for member in members:
                if member.file_size > MAX_FILE_BYTES or stat.S_ISLNK(member.external_attr >> 16):
                    raise OSError("invalid artifact archive member")
                _write_host_file(root, member.filename, archive.read(member))
    finally:
        sandbox.remote.delete_file(remote_path)


def upload_inputs(sandbox, root: Path, destination: str):
    """Hydrate embedded-client uploads and ACP inputs on acquire."""
    if not root.exists():
        return
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise PermissionError("input root contains a symlink")
    count = total = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.name.startswith(".upload-"):
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            raise PermissionError("input escapes thread directory")
        size = path.stat().st_size
        count += 1
        total += size
        if count > MAX_FILES or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise OSError("input transfer limit exceeded")
        sandbox.update_file(f"{destination}/{path.relative_to(root).as_posix()}", path.read_bytes())
