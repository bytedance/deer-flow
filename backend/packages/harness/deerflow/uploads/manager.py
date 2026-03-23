"""Shared upload management logic.

Pure business logic — no FastAPI/HTTP dependencies.
Both Gateway and Client delegate to these functions.
"""

import os
from pathlib import Path

from deerflow.config.paths import get_paths


def get_uploads_dir(thread_id: str) -> Path:
    """Return the uploads directory path for a thread (no side effects)."""
    return get_paths().sandbox_uploads_dir(thread_id)


def ensure_uploads_dir(thread_id: str) -> Path:
    """Return the uploads directory for a thread, creating it if needed."""
    base = get_uploads_dir(thread_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_filename(filename: str) -> str:
    """Sanitize a filename by extracting its basename.

    Strips any directory components and rejects traversal patterns.

    Args:
        filename: Raw filename from user input (may contain path components).

    Returns:
        Safe filename (basename only).

    Raises:
        ValueError: If filename is empty or resolves to a traversal pattern.
    """
    if not filename:
        raise ValueError("Filename is empty")
    safe = Path(filename).name
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")
    # Reject backslashes — on Linux Path.name keeps them as literal chars,
    # but they indicate a Windows-style path that should be stripped or rejected.
    if "\\" in safe:
        raise ValueError(f"Filename contains backslash: {filename!r}")
    return safe


def deduplicate_filename(name: str, seen: set[str]) -> str:
    """Generate a unique filename by appending ``_N`` suffix on collision.

    Does NOT mutate *seen*.

    Args:
        name: Candidate filename.
        seen: Set of filenames already claimed.

    Returns:
        A filename not present in *seen*.
    """
    if name not in seen:
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    candidate = f"{stem}_{counter}{suffix}"
    while candidate in seen:
        counter += 1
        candidate = f"{stem}_{counter}{suffix}"
    return candidate


def validate_path_traversal(path: Path, base: Path) -> None:
    """Verify that *path* is inside *base*.

    Raises:
        PermissionError: If a path traversal is detected.
    """
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise PermissionError("Access denied: path traversal detected") from None


def list_files_in_dir(directory: Path) -> dict:
    """List files (not directories) in *directory*.

    Args:
        directory: Directory to scan.

    Returns:
        Dict with "files" list (sorted by name) and "count".
    """
    if not directory.exists():
        return {"files": [], "count": 0}

    files = []
    with os.scandir(directory) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if not entry.is_file():
                continue
            st = entry.stat()
            files.append({
                "filename": entry.name,
                "size": st.st_size,
                "path": entry.path,
                "extension": Path(entry.name).suffix,
                "modified": st.st_mtime,
            })
    return {"files": files, "count": len(files)}


def delete_file_safe(base_dir: Path, filename: str) -> dict:
    """Delete a file inside *base_dir* after path-traversal validation.

    Args:
        base_dir: Directory containing the file.
        filename: Name of file to delete.

    Returns:
        Dict with success and message.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionError: If path traversal is detected.
    """
    file_path = (base_dir / filename).resolve()
    validate_path_traversal(file_path, base_dir)

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")

    file_path.unlink()
    return {"success": True, "message": f"Deleted {filename}"}
