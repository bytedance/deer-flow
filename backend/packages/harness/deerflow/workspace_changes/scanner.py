from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
from pathlib import Path

from .types import (
    DiffUnavailableReason,
    FileSnapshot,
    WorkspaceChangeLimits,
    WorkspaceRoot,
    WorkspaceSnapshot,
)

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".cache",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

BINARY_EXTENSIONS = {
    ".7z",
    ".avif",
    ".bmp",
    ".class",
    ".db",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".tar",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}

SENSITIVE_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*api_key*",
    "*apikey*",
    "*.key",
    "*.pem",
    "*credential*",
    "*password*",
    "*private_key*",
    "*secret*",
    "*token*",
)

SAMPLE_BYTES = 4096


def is_sensitive_workspace_path(path: str) -> bool:
    normalized = path.lower()
    parts = [part.lower() for part in Path(path).parts]
    basename = parts[-1] if parts else normalized
    for pattern in SENSITIVE_PATH_PATTERNS:
        if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(normalized, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def scan_workspace_roots(
    roots: list[WorkspaceRoot],
    *,
    limits: WorkspaceChangeLimits | None = None,
    include_text: bool = True,
    text_paths: set[str] | None = None,
    text_cache_dir: Path | None = None,
) -> WorkspaceSnapshot:
    resolved_limits = limits or WorkspaceChangeLimits()
    cache_dir = Path(text_cache_dir) if text_cache_dir is not None else None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, FileSnapshot] = {}
    scanned = 0
    truncated = False

    for root in roots:
        if not root.host_path.exists():
            continue

        for dirpath, dirnames, filenames in os.walk(root.host_path, followlinks=False):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in EXCLUDED_DIR_NAMES and not (Path(dirpath) / dirname).is_symlink()]
            for filename in sorted(filenames):
                if scanned >= resolved_limits.max_scanned_files:
                    truncated = True
                    return WorkspaceSnapshot(
                        files=files,
                        truncated=truncated,
                        text_cache_dir=str(cache_dir) if cache_dir is not None else None,
                    )

                host_file = Path(dirpath) / filename
                if host_file.is_symlink() or not host_file.is_file():
                    continue

                snapshot = _snapshot_file(
                    root,
                    host_file,
                    limits=resolved_limits,
                    include_text=include_text,
                    text_paths=text_paths,
                    text_cache_dir=cache_dir,
                )
                if snapshot is not None:
                    files[snapshot.path] = snapshot
                    scanned += 1

    return WorkspaceSnapshot(
        files=files,
        truncated=truncated,
        text_cache_dir=str(cache_dir) if cache_dir is not None else None,
    )


def _snapshot_file(
    root: WorkspaceRoot,
    host_file: Path,
    *,
    limits: WorkspaceChangeLimits,
    include_text: bool,
    text_paths: set[str] | None,
    text_cache_dir: Path | None,
) -> FileSnapshot | None:
    try:
        stat = host_file.stat()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns
        relative = host_file.relative_to(root.host_path).as_posix()
        virtual_path = f"{root.virtual_prefix}/{relative}"
        sensitive = is_sensitive_workspace_path(virtual_path)
    except OSError:
        return None

    if sensitive:
        return FileSnapshot(
            path=virtual_path,
            root=root.name,
            size=size,
            mtime_ns=mtime_ns,
            sha256=None,
            binary=False,
            sensitive=True,
            text=None,
            content_unavailable_reason="sensitive",
        )

    try:
        sample = host_file.read_bytes()[:SAMPLE_BYTES] if size <= SAMPLE_BYTES else _read_sample(host_file)
    except OSError:
        return None

    binary = host_file.suffix.lower() in BINARY_EXTENSIONS or _looks_binary(sample)
    sha256 = _sha256_file(host_file) if size <= limits.max_file_bytes_for_diff else None
    text: str | None = None
    text_path: str | None = None
    reason: DiffUnavailableReason | None = None

    should_include_text = include_text and (text_paths is None or virtual_path in text_paths)

    if binary:
        reason = "binary"
    elif size > limits.max_file_bytes_for_diff:
        reason = "large"
    elif not should_include_text:
        text = None
    elif text_cache_dir is not None:
        text_path = str(_cache_text_file(host_file, virtual_path, text_cache_dir))
    else:
        try:
            text = host_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            binary = True
            reason = "binary"
        except OSError:
            return None

    return FileSnapshot(
        path=virtual_path,
        root=root.name,
        size=size,
        mtime_ns=mtime_ns,
        sha256=sha256,
        binary=binary,
        sensitive=sensitive,
        text=text,
        text_path=text_path,
        content_unavailable_reason=reason,
    )


def _cache_text_file(source: Path, virtual_path: str, cache_dir: Path) -> Path:
    cache_name = hashlib.sha256(virtual_path.encode("utf-8")).hexdigest()
    target = cache_dir / cache_name
    shutil.copyfile(source, target)
    return target


def _read_sample(path: Path) -> bytes:
    with path.open("rb") as file:
        return file.read(SAMPLE_BYTES)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False
