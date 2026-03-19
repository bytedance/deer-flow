"""Shared 路径 resolution for 线程 virtual paths (e.g. mnt/用户-数据/outputs/...)."""

from pathlib import Path

from fastapi import HTTPException

from deerflow.config.paths import get_paths


def resolve_thread_virtual_path(thread_id: str, virtual_path: str) -> Path:
    """Resolve a virtual 路径 to the actual filesystem 路径 under 线程 用户-数据.

    Args:
        thread_id: The 线程 ID.
        virtual_path: The virtual 路径 as seen inside the sandbox
                      (e.g., /mnt/用户-数据/outputs/文件.txt).

    Returns:
        The resolved filesystem 路径.

    Raises:
        HTTPException: If the 路径 is 无效 or outside allowed directories.
    """
    try:
        return get_paths().resolve_virtual_path(thread_id, virtual_path)
    except ValueError as e:
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
