"""Shared path resolution for thread virtual paths (e.g. mnt/user-data/outputs/...)."""

import posixpath
from pathlib import Path

from fastapi import HTTPException

from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from deerflow.runtime.user_context import get_effective_user_id

OUTPUTS_VIRTUAL_ROOT = f"{VIRTUAL_PATH_PREFIX}/outputs"
_OUTPUTS_PREFIX = OUTPUTS_VIRTUAL_ROOT.lstrip("/") + "/"
_OUTPUTS_ONLY_DETAIL = f"Only files under {OUTPUTS_VIRTUAL_ROOT} are allowed"


def resolve_thread_virtual_path(thread_id: str, virtual_path: str, user_id: str | None = None) -> Path:
    """Resolve a virtual path to the actual filesystem path under thread user-data.

    Args:
        thread_id: The thread ID.
        virtual_path: The virtual path as seen inside the sandbox
                      (e.g., /mnt/user-data/outputs/file.txt).
        user_id: The user whose storage to resolve under. Defaults to the
                 effective user when not given; callers acting on behalf of a
                 specific owner (e.g. trusted internal callers) pass it explicitly.

    Returns:
        The resolved filesystem path.

    Raises:
        HTTPException: If the path is invalid or outside allowed directories.
    """
    try:
        return get_paths().resolve_virtual_path(thread_id, virtual_path, user_id=user_id or get_effective_user_id())
    except ValueError as e:
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


def normalize_outputs_virtual_path(virtual_path: str) -> str:
    """Return *virtual_path* as a canonical ``/mnt/user-data/outputs/...`` path.

    ``.``/``..`` segments and duplicate slashes are collapsed *before* the
    prefix check, so ``outputs/../uploads/x`` (or its percent-encoded form,
    which nginx forwards untouched and Starlette decodes) is rejected as a
    non-outputs path instead of slipping past a raw string-prefix test. The
    outputs directory itself is not a file and is rejected too.

    Raises:
        HTTPException: 400 when the path is not strictly inside outputs.
    """
    stripped = posixpath.normpath(virtual_path.lstrip("/")).lstrip("/")
    if not stripped.startswith(_OUTPUTS_PREFIX):
        raise HTTPException(status_code=400, detail=_OUTPUTS_ONLY_DETAIL)
    return f"/{stripped}"


def resolve_outputs_confined_path(thread_id: str, virtual_path: str, user_id: str | None = None) -> Path:
    """Resolve *virtual_path* and guarantee it lives inside the thread's outputs dir.

    ``resolve_thread_virtual_path`` only confines to ``user-data/``. Callers
    that must never touch uploads, workspace, or tool results (the artifact
    editor, IM-channel attachment delivery) go through this helper so the
    outputs rule lives in one place: the path is normalized lexically first,
    then the resolved host path is checked against the resolved outputs root,
    which also catches a symlink planted inside ``outputs/``.

    Existence is not checked; callers decide how a missing file surfaces.

    Raises:
        HTTPException: 400 when the path is not strictly inside outputs; 403
            when the underlying resolver detects traversal above ``user-data/``.
    """
    normalized = normalize_outputs_virtual_path(virtual_path)
    resolved_user_id = user_id or get_effective_user_id()
    actual_path = resolve_thread_virtual_path(thread_id, normalized, user_id=resolved_user_id)
    outputs_root = get_paths().sandbox_outputs_dir(thread_id, user_id=resolved_user_id).resolve()
    if actual_path == outputs_root or not actual_path.is_relative_to(outputs_root):
        raise HTTPException(status_code=400, detail=_OUTPUTS_ONLY_DETAIL)
    return actual_path
