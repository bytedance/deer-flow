"""Private checkpoint write identity and final publication boundary.

Build graphs and prepare mutations outside these locks. Only native prepared
checkpoint IO belongs in commit; run admission/reservation remains authoritative.
"""

from contextlib import aclosing

from fastapi import HTTPException, Request

from app.gateway.deps import get_checkpointer, get_thread_store
from deerflow.authz.workspace import get_current_workspace
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied


async def capture_checkpoint_thread_identity(request: Request, thread_id: str) -> str | None:
    context = get_current_workspace()
    if context is None:
        return None
    repository = get_thread_store(request)
    if not isinstance(repository, ThreadMetaRepository):
        raise HTTPException(status_code=503, detail="Checkpoint writes require persistent workspace scope")
    admitted = getattr(request.state, "workspace_checkpoint_identity", None)
    if admitted is not None and (not isinstance(admitted, tuple) or len(admitted) != 4 or admitted[:3] != (context.workspace_id, context.actor_user_id, thread_id)):
        raise WorkspaceAccessDenied("checkpoint admission identity does not match caller")
    row = await repository.get(thread_id, user_id=context.actor_user_id)
    incarnation = row.get("incarnation") if row is not None else None
    if not isinstance(incarnation, str) or not incarnation:
        raise WorkspaceAccessDenied("private checkpoint thread is unavailable")
    if admitted is not None and admitted[3] != incarnation:
        raise WorkspaceAccessDenied("checkpoint thread changed during owner admission")
    return incarnation


async def commit_checkpoint_write(request: Request, thread_id: str, *, incarnation: str | None, commit):
    context = get_current_workspace()
    if context is None:
        return await commit()
    repository = get_thread_store(request)
    if not isinstance(repository, ThreadMetaRepository):
        raise HTTPException(status_code=503, detail="Checkpoint writes require persistent workspace scope")
    return await repository.commit_checkpoint_under_live_lock(thread_id, incarnation=incarnation, commit=commit, user_id=context.actor_user_id)


async def require_unallocated_checkpoint_id(request: Request, thread_id: str) -> None:
    """Refuse metadata allocation over any unattributed checkpoint namespace.

    This is an occupancy probe, not permission to return checkpoint content.
    A missing namespace selector deliberately checks root and subgraph records.
    Legacy unbound allocation keeps its native behavior. Mixed-version writers
    still require the rollout fence; this read is not a cross-store transaction.
    """
    if get_current_workspace() is None:
        return
    try:
        config = {"configurable": {"thread_id": thread_id}}
        async with aclosing(get_checkpointer(request).alist(config, limit=1)) as entries:
            async for _ in entries:
                raise WorkspaceAccessDenied("thread identity is unavailable")
    except WorkspaceAccessDenied:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Checkpoint identity validation unavailable") from None
