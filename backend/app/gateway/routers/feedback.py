"""Feedback endpoints — create, list, stats, delete.

Allows users to submit thumbs-up/down feedback on runs,
optionally scoped to a specific message.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user, get_feedback_repo, get_run_store
from app.gateway.workspaces.checkpoints import capture_checkpoint_thread_identity
from app.gateway.workspaces.dependencies import workspace_resource_scope
from deerflow.authz.workspace import get_current_workspace
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["feedback"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class FeedbackCreateRequest(BaseModel):
    rating: int = Field(..., description="Feedback rating: +1 (positive) or -1 (negative)")
    comment: str | None = Field(default=None, description="Optional text feedback")
    message_id: str | None = Field(default=None, description="Optional: scope feedback to a specific message")


class FeedbackUpsertRequest(BaseModel):
    rating: int = Field(..., description="Feedback rating: +1 (positive) or -1 (negative)")
    comment: str | None = Field(default=None, description="Optional text feedback")


class FeedbackResponse(BaseModel):
    feedback_id: str
    run_id: str
    thread_id: str
    user_id: str | None = None
    message_id: str | None = None
    rating: int
    comment: str | None = None
    created_at: str = ""


class FeedbackStatsResponse(BaseModel):
    run_id: str
    total: int = 0
    positive: int = 0
    negative: int = 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def _require_feedback_run(request: Request, thread_id: str, run_id: str, *, required_in_native=False):
    context = get_current_workspace()
    if context is None and not required_in_native:
        return
    store = get_run_store(request)
    run = await store.get(run_id, user_id=context.actor_user_id) if context is not None else await store.get(run_id)
    if run is None or run.get("thread_id") != thread_id:
        raise HTTPException(status_code=404, detail="Run not found")


def _feedback_owner_kwargs():
    context = get_current_workspace()
    return {"user_id": context.actor_user_id} if context is not None else {}


async def _feedback_identity_kwargs(request: Request, thread_id: str):
    if get_current_workspace() is None:
        return {}
    return {"incarnation": await capture_checkpoint_thread_identity(request, thread_id)}


@router.put("/{thread_id}/runs/{run_id}/feedback", response_model=FeedbackResponse)
@workspace_resource_scope(private_thread_read=True)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def upsert_feedback(
    thread_id: ThreadId,
    run_id: str,
    body: FeedbackUpsertRequest,
    request: Request,
) -> dict[str, Any]:
    """Create or update feedback for a run (idempotent)."""
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be +1 or -1")

    user_id = await get_current_user(request)

    await _require_feedback_run(request, thread_id, run_id, required_in_native=True)

    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.upsert(
        run_id=run_id,
        thread_id=thread_id,
        rating=body.rating,
        user_id=user_id,
        comment=body.comment,
        **(await _feedback_identity_kwargs(request, thread_id)),
    )


@router.delete("/{thread_id}/runs/{run_id}/feedback")
@workspace_resource_scope(private_thread_read=True)
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_run_feedback(
    thread_id: ThreadId,
    run_id: str,
    request: Request,
) -> dict[str, bool]:
    """Delete the current user's feedback for a run."""
    await _require_feedback_run(request, thread_id, run_id)
    user_id = await get_current_user(request)
    feedback_repo = get_feedback_repo(request)
    deleted = await feedback_repo.delete_by_run(
        thread_id=thread_id,
        run_id=run_id,
        user_id=user_id,
        **(await _feedback_identity_kwargs(request, thread_id)),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="No feedback found for this run")
    return {"success": True}


@router.post("/{thread_id}/runs/{run_id}/feedback", response_model=FeedbackResponse)
@workspace_resource_scope(private_thread_read=True)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def create_feedback(
    thread_id: ThreadId,
    run_id: str,
    body: FeedbackCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Submit feedback (thumbs-up/down) for a run."""
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be +1 or -1")

    user_id = await get_current_user(request)

    await _require_feedback_run(request, thread_id, run_id, required_in_native=True)

    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.create(
        run_id=run_id,
        thread_id=thread_id,
        rating=body.rating,
        user_id=user_id,
        message_id=body.message_id,
        comment=body.comment,
        **(await _feedback_identity_kwargs(request, thread_id)),
    )


@router.get("/{thread_id}/runs/{run_id}/feedback", response_model=list[FeedbackResponse])
@workspace_resource_scope(private_thread_read=True)
@require_permission("threads", "read", owner_check=True)
async def list_feedback(
    thread_id: ThreadId,
    run_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    """List all feedback for a run."""
    feedback_repo = get_feedback_repo(request)
    await _require_feedback_run(request, thread_id, run_id)
    return await feedback_repo.list_by_run(thread_id, run_id, **_feedback_owner_kwargs())


@router.get("/{thread_id}/runs/{run_id}/feedback/stats", response_model=FeedbackStatsResponse)
@workspace_resource_scope(private_thread_read=True)
@require_permission("threads", "read", owner_check=True)
async def feedback_stats(
    thread_id: ThreadId,
    run_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get aggregated feedback stats (positive/negative counts) for a run."""
    feedback_repo = get_feedback_repo(request)
    await _require_feedback_run(request, thread_id, run_id)
    return await feedback_repo.aggregate_by_run(thread_id, run_id, **_feedback_owner_kwargs())


@router.delete("/{thread_id}/runs/{run_id}/feedback/{feedback_id}")
@workspace_resource_scope(private_thread_read=True)
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_feedback(
    thread_id: ThreadId,
    run_id: str,
    feedback_id: str,
    request: Request,
) -> dict[str, bool]:
    """Delete a feedback record."""
    feedback_repo = get_feedback_repo(request)
    # Verify feedback belongs to the specified thread/run before deleting
    await _require_feedback_run(request, thread_id, run_id)
    existing = await feedback_repo.get(feedback_id, **_feedback_owner_kwargs())
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found")
    if existing.get("thread_id") != thread_id or existing.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found in run {run_id}")
    deleted = await feedback_repo.delete(feedback_id, **_feedback_owner_kwargs(), **(await _feedback_identity_kwargs(request, thread_id)))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found")
    return {"success": True}
