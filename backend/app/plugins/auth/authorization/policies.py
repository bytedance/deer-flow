"""Authorization policies for resource ownership and access checks."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app.plugins.auth.authorization.types import AuthContext


def _get_thread_owner_id(thread_meta: Any) -> str | None:
    owner_id = getattr(thread_meta, "user_id", None)
    if owner_id is not None:
        return str(owner_id)

    metadata = getattr(thread_meta, "metadata", None) or {}
    metadata_owner_id = metadata.get("user_id")
    if metadata_owner_id is not None:
        return str(metadata_owner_id)
    return None


async def _thread_exists_via_legacy_sources(request: Request, auth: AuthContext, *, thread_id: str) -> bool:
    from app.gateway.dependencies.repositories import get_run_repository

    principal_id = auth.principal_id
    run_store = get_run_repository(request)
    runs = await run_store.list_by_thread(
        thread_id,
        limit=1,
        user_id=principal_id,
    )
    if runs:
        return True

    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is None:
        return False

    checkpoint_tuple = await checkpointer.aget_tuple(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    )
    return checkpoint_tuple is not None


async def require_thread_owner(
    request: Request,
    auth: AuthContext,
    *,
    thread_id: str,
    require_existing: bool,
) -> None:
    """Ensure the current user owns the thread referenced by ``thread_id``."""

    from app.gateway.dependencies.repositories import get_thread_meta_repository

    thread_repo = get_thread_meta_repository(request)
    thread_meta = await thread_repo.get_thread_meta(thread_id)
    if thread_meta is None:
        allowed = not require_existing
        if not allowed:
            allowed = await _thread_exists_via_legacy_sources(request, auth, thread_id=thread_id)
    else:
        owner_id = _get_thread_owner_id(thread_meta)
        allowed = owner_id in (None, str(auth.user.id))

    if not allowed:
        raise HTTPException(
            status_code=404,
            detail=f"Thread {thread_id} not found",
        )


async def require_run_owner(
    request: Request,
    auth: AuthContext,
    *,
    thread_id: str,
    run_id: str,
    require_existing: bool,
) -> None:
    """Ensure the current user owns the run referenced by ``run_id``."""

    from app.gateway.dependencies import get_run_repository

    run_store = get_run_repository(request)
    run = await run_store.get(run_id)
    if run is None:
        allowed = not require_existing
    else:
        allowed = run.get("thread_id") == thread_id

    if not allowed:
        raise HTTPException(
            status_code=404,
            detail=f"Run {run_id} not found",
        )


__all__ = ["require_run_owner", "require_thread_owner"]
