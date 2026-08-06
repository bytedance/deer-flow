"""Path and URL layout helpers for primary uploads and generated assets."""

import hashlib
import os
import stat
from pathlib import Path
from urllib.parse import quote

from deerflow.config.paths import VIRTUAL_PATH_PREFIX

UPLOAD_CONVERSIONS_DIRNAME = ".upload-conversions"
UPLOAD_LOCKS_DIRNAME = ".locks"


class UnsafeConversionPathError(ValueError):
    """Raised when the generated-conversion namespace is unsafe."""


def conversion_dir_for_uploads(uploads_dir: Path) -> Path:
    """Return the system-owned conversion directory beside ``uploads_dir``."""
    return uploads_dir.parent / UPLOAD_CONVERSIONS_DIRNAME


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def conversion_filename_for_upload(filename: str) -> str:
    """Return a deterministic generated-Markdown component within 255 bytes."""
    desired = f"{filename}.md"
    if len(desired.encode("utf-8")) <= 255:
        return desired
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()
    marker = f".{digest}.md"
    prefix = _truncate_utf8(filename, 255 - len(marker.encode("utf-8")))
    return f"{prefix}{marker}"


def conversion_path_for_upload(upload_path: Path) -> Path:
    """Return the generated Markdown path owned by one primary upload."""
    return conversion_dir_for_uploads(upload_path.parent) / conversion_filename_for_upload(upload_path.name)


def validate_conversion_dir(uploads_dir: Path) -> Path | None:
    """Return an existing real conversion directory without following links."""
    conversion_dir = conversion_dir_for_uploads(uploads_dir)
    try:
        conversion_stat = os.lstat(conversion_dir)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(conversion_stat.st_mode) or not stat.S_ISDIR(conversion_stat.st_mode):
        raise UnsafeConversionPathError("Unsafe upload conversion directory")
    return conversion_dir


def ensure_conversion_dir(uploads_dir: Path) -> Path:
    """Create and validate the system-owned conversion directory."""
    conversion_dir = conversion_dir_for_uploads(uploads_dir)
    try:
        conversion_dir.mkdir(mode=0o755)
    except FileExistsError:
        pass
    validated = validate_conversion_dir(uploads_dir)
    if validated is None:
        raise UnsafeConversionPathError("Upload conversion directory disappeared")
    return validated


def upload_lock_dir_for_uploads(uploads_dir: Path) -> Path:
    """Return the stable per-upload lock directory."""
    return conversion_dir_for_uploads(uploads_dir) / UPLOAD_LOCKS_DIRNAME


def ensure_upload_lock_dir(uploads_dir: Path) -> Path:
    """Create and validate the system-owned upload lock directory."""
    conversion_dir = ensure_conversion_dir(uploads_dir)
    lock_dir = conversion_dir / UPLOAD_LOCKS_DIRNAME
    try:
        lock_dir.mkdir(mode=0o700)
    except FileExistsError:
        pass
    try:
        lock_stat = os.lstat(lock_dir)
    except FileNotFoundError as exc:
        raise UnsafeConversionPathError("Upload lock directory disappeared") from exc
    if stat.S_ISLNK(lock_stat.st_mode) or not stat.S_ISDIR(lock_stat.st_mode):
        raise UnsafeConversionPathError("Unsafe upload lock directory")
    return lock_dir


def existing_conversion_path_for_upload(upload_path: Path) -> Path | None:
    """Return an existing safe generated file owned by ``upload_path``."""
    if validate_conversion_dir(upload_path.parent) is None:
        return None
    candidate = conversion_path_for_upload(upload_path)
    try:
        candidate_stat = os.lstat(candidate)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_nlink != 1:
        raise UnsafeConversionPathError("Unsafe upload conversion file")
    return candidate


def upload_virtual_path(filename: str) -> str:
    """Build the sandbox virtual path for a primary upload."""
    return f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"


def conversion_virtual_path(filename: str) -> str:
    """Build the sandbox virtual path for an upload's generated Markdown."""
    return f"{VIRTUAL_PATH_PREFIX}/{UPLOAD_CONVERSIONS_DIRNAME}/{conversion_filename_for_upload(filename)}"


def artifact_url_for_virtual_path(thread_id: str, virtual_path: str) -> str:
    """Build an artifact URL while preserving path separators."""
    return f"/api/threads/{thread_id}/artifacts{quote(virtual_path, safe='/')}"
