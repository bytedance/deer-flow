"""Shared path resolution for thread virtual paths (e.g. mnt/user-data/outputs/...)."""

import re
from pathlib import Path

from fastapi import HTTPException

from src.config.paths import get_paths

_THREAD_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def validate_thread_id(thread_id: str) -> None:
    """Validate that a thread_id looks safe (alphanumeric / UUID-style).

    Raises HTTPException 400 if the format is unexpected.
    """
    if not _THREAD_ID_PATTERN.match(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread_id format")


def resolve_thread_virtual_path(thread_id: str, virtual_path: str) -> Path:
    """Resolve a virtual path to the actual filesystem path under thread user-data.

    Args:
        thread_id: The thread ID.
        virtual_path: The virtual path as seen inside the sandbox
                      (e.g., /mnt/user-data/outputs/file.txt).

    Returns:
        The resolved filesystem path.

    Raises:
        HTTPException: If the path is invalid or outside allowed directories.
    """
    validate_thread_id(thread_id)
    try:
        return get_paths().resolve_virtual_path(thread_id, virtual_path)
    except ValueError as e:
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
