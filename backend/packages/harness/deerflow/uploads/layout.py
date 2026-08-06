"""Path and URL layout helpers for primary uploads and generated assets."""

from pathlib import Path
from urllib.parse import quote

from deerflow.config.paths import VIRTUAL_PATH_PREFIX

UPLOAD_CONVERSIONS_DIRNAME = ".upload-conversions"


def conversion_dir_for_uploads(uploads_dir: Path) -> Path:
    """Return the system-owned conversion directory beside ``uploads_dir``."""
    return uploads_dir.parent / UPLOAD_CONVERSIONS_DIRNAME


def conversion_path_for_upload(upload_path: Path) -> Path:
    """Return the generated Markdown path owned by one primary upload."""
    return conversion_dir_for_uploads(upload_path.parent) / f"{upload_path.name}.md"


def upload_virtual_path(filename: str) -> str:
    """Build the sandbox virtual path for a primary upload."""
    return f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"


def conversion_virtual_path(filename: str) -> str:
    """Build the sandbox virtual path for an upload's generated Markdown."""
    return f"{VIRTUAL_PATH_PREFIX}/{UPLOAD_CONVERSIONS_DIRNAME}/{filename}.md"


def artifact_url_for_virtual_path(thread_id: str, virtual_path: str) -> str:
    """Build an artifact URL while preserving path separators."""
    return f"/api/threads/{thread_id}/artifacts{quote(virtual_path, safe='/')}"
