"""Shared path resolution for thread virtual paths (e.g. mnt/user-data/outputs/...)."""

import os
from pathlib import Path

from fastapi import HTTPException

from src.agents.middlewares.thread_data_middleware import THREAD_DATA_BASE_DIR

# Virtual path prefix used in sandbox environments (without leading slash for URL path matching)
VIRTUAL_PATH_PREFIX = "mnt/user-data"


def resolve_thread_virtual_path(thread_id: str, virtual_path: str) -> Path:
    """Resolve a virtual path to the actual filesystem path under thread user-data.

    Args:
        thread_id: The thread ID.
        virtual_path: The virtual path (e.g., mnt/user-data/outputs/file.txt).
                      Leading slashes are stripped.

    Returns:
        The resolved filesystem path.

    Raises:
        HTTPException: If the path is invalid or outside allowed directories.
    """
    virtual_path = virtual_path.lstrip("/")
    if not virtual_path.startswith(VIRTUAL_PATH_PREFIX):
        raise HTTPException(status_code=400, detail=f"Path must start with /{VIRTUAL_PATH_PREFIX}")
    relative_path = virtual_path[len(VIRTUAL_PATH_PREFIX) :].lstrip("/")

    base_dir = Path(os.getcwd()) / THREAD_DATA_BASE_DIR / thread_id / "user-data"
    actual_path = base_dir / relative_path

    try:
        actual_path = actual_path.resolve()
        base_resolved = base_dir.resolve()
        if not str(actual_path).startswith(str(base_resolved)):
            raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=400, detail="Invalid path")

    return actual_path
