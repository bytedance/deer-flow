"""Path and URL layout helpers for primary uploads and generated assets."""

import os
import stat
from pathlib import Path
from urllib.parse import quote

from deerflow.config.paths import VIRTUAL_PATH_PREFIX

UPLOAD_CONVERSIONS_DIRNAME = ".upload-conversions"


class UnsafeConversionPathError(ValueError):
    """Raised when the generated-conversion namespace is unsafe."""


def conversion_dir_for_uploads(uploads_dir: Path) -> Path:
    """Return the system-owned conversion directory beside ``uploads_dir``."""
    return uploads_dir.parent / UPLOAD_CONVERSIONS_DIRNAME


def conversion_path_for_upload(upload_path: Path) -> Path:
    """Return the generated Markdown path owned by one primary upload."""
    return conversion_dir_for_uploads(upload_path.parent) / f"{upload_path.name}.md"


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
    return f"{VIRTUAL_PATH_PREFIX}/{UPLOAD_CONVERSIONS_DIRNAME}/{filename}.md"


def artifact_url_for_virtual_path(thread_id: str, virtual_path: str) -> str:
    """Build an artifact URL while preserving path separators."""
    return f"/api/threads/{thread_id}/artifacts{quote(virtual_path, safe='/')}"
