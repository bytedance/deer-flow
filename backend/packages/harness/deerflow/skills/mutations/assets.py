"""Bounded byte snapshots for managed custom packages (POSIX, no links)."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from deerflow.skills.mutations.validation import MAX_MAIN_BYTES

MAX_FILES = 256
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 24


@dataclass(frozen=True)
class PackageFile:
    path: str
    content: bytes
    executable: bool

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class PackageSnapshot:
    files: tuple[PackageFile, ...]

    @property
    def main_content(self) -> str:
        return next(item.content for item in self.files if item.path == "SKILL.md").decode("utf-8")

    @property
    def digest(self) -> str:
        manifest = [(item.path, item.digest, item.executable) for item in self.files]
        return hashlib.sha256(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

    def with_main(self, content: str) -> PackageSnapshot:
        return PackageSnapshot(tuple(PackageFile(item.path, content.encode("utf-8"), item.executable) if item.path == "SKILL.md" else item for item in self.files))


def capture_package(root: Path) -> PackageSnapshot:
    """Caller owns mutation guard. Never read outside the opened package tree."""
    if os.name != "posix":
        raise ValueError("UNSUPPORTED_ASSET")
    files: list[PackageFile] = []
    total = 0
    entries = 0
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK

    def walk(directory_fd: int, prefix: str = "", depth: int = 0) -> None:
        nonlocal total, entries
        if depth > MAX_DEPTH:
            raise ValueError("QUOTA_EXCEEDED")
        # Bound directory enumeration, including empty directories, before sort.
        names = []
        with os.scandir(directory_fd) as iterator:
            for entry in iterator:
                entries += 1
                if entries > MAX_FILES * 2:
                    raise ValueError("QUOTA_EXCEEDED")
                names.append(entry.name)
        for name in sorted(names):
            if "\\" in name or any(ord(c) < 32 for c in name):
                raise ValueError("UNSUPPORTED_ASSET")
            path = f"{prefix}/{name}" if prefix else name
            if len(path.encode("utf-8")) > 1024:
                raise ValueError("QUOTA_EXCEEDED")
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                raise ValueError("UNSUPPORTED_ASSET")
            fd = os.open(name, flags | (os.O_DIRECTORY if stat.S_ISDIR(info.st_mode) else 0), dir_fd=directory_fd)
            try:
                opened = os.fstat(fd)
                if (info.st_dev, info.st_ino, info.st_mode) != (opened.st_dev, opened.st_ino, opened.st_mode):
                    raise ValueError("REVISION_CONFLICT")
                if stat.S_ISDIR(opened.st_mode):
                    walk(fd, path, depth + 1)
                    continue
                if len(files) >= MAX_FILES:
                    raise ValueError("QUOTA_EXCEEDED")
                limit = min(MAX_PACKAGE_BYTES - total, MAX_MAIN_BYTES if path == "SKILL.md" else MAX_PACKAGE_BYTES)
                if opened.st_size > limit:
                    raise ValueError("QUOTA_EXCEEDED")
                data = bytearray()
                while True:
                    chunk = os.read(fd, min(65536, limit + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ValueError("QUOTA_EXCEEDED")
                after = os.fstat(fd)
                if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError("REVISION_CONFLICT")
                total += len(data)
                files.append(PackageFile(path, bytes(data), bool(opened.st_mode & 0o111)))
            finally:
                os.close(fd)

    try:
        root_fd = open_directory_chain(root)
        try:
            walk(root_fd)
        finally:
            os.close(root_fd)
    except OSError as exc:
        raise ValueError("UNSUPPORTED_ASSET") from exc
    result = PackageSnapshot(tuple(sorted(files, key=lambda item: item.path)))
    try:
        result.main_content
    except (StopIteration, UnicodeError) as exc:
        raise ValueError("UNSUPPORTED_ASSET") from exc
    return result


def open_directory_chain(path: Path) -> int:
    """Return an anchored directory FD; reject links in every ancestor.

    Publication also uses this helper: validating only the package's final
    component would let a linked owner/custom root escape the owner guard.
    Caller owns the returned descriptor.
    """
    path = path.absolute()
    if ".." in path.parts or len(path.parts) > 128 or len(os.fsencode(path)) > 4096:
        raise ValueError("UNSUPPORTED_ASSET")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            before = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ValueError("UNSUPPORTED_ASSET")
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_mode) != (after.st_dev, after.st_ino, after.st_mode):
                raise ValueError("REVISION_CONFLICT")
        return fd
    except BaseException:
        os.close(fd)
        raise
