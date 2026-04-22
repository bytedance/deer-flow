"""LangGraph-compatible run feedback endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.dependencies import get_feedback_repository, get_run_repository
from app.plugins.auth.security.actor_context import bind_request_actor_context, resolve_request_user_id
from app.plugins.auth.security.dependencies import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["feedback"])


class FeedbackCreateRequest(BaseModel):
    rating: int = Field(..., description="Feedback rating: +1 (positive) or -1 (negative)")
    comment: str | None = Field(default=None, description="Optional text feedback")
    message_id: str | None = Field(default=None, description="Optional: scope feedback to a specific message")


class FeedbackResponse(BaseModel):
    feedback_id: str
    run_id: str
    thread_id: str
    owner_id: str | None = None
    message_id: str | None = None
    rating: int
    comment: str | None = None
    created_at: str = ""


class FeedbackStatsResponse(BaseModel):
    run_id: str
    total: int = 0
    positive: int = 0
    negative: int = 0


async def _validate_run_scope(thread_id: str, run_id: str, request: Request) -> None:
    run_store = get_run_repository(request)
    if resolve_request_user_id(request) is None:
        run = await run_store.get(run_id, user_id=None)
    else:
        with bind_request_actor_context(request):
            run = await run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.get("thread_id") != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in thread {thread_id}")


async def _get_current_user(request: Request) -> str | None:
    """Extract current user id from auth dependencies when available."""
    return await get_current_user_id(request)


async def _create_feedback(
    thread_id: str,
    run_id: str,
    body: FeedbackCreateRequest,
    request: Request,
) -> dict[str, Any]:
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be +1 or -1")

    await _validate_run_scope(thread_id, run_id, request)
    user_id = await _get_current_user(request)
    feedback_repo = get_feedback_repository(request)
    return await feedback_repo.create(
        run_id=run_id,
        thread_id=thread_id,
        rating=body.rating,
        user_id=user_id,
        message_id=body.message_id,
        comment=body.comment,
    )


@router.put("/{thread_id}/runs/{run_id}/feedback", response_model=FeedbackResponse)
async def upsert_feedback(
    thread_id: str,
    run_id: str,
    body: FeedbackCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Create or replace the run-level feedback record."""
    feedback_repo = get_feedback_repository(request)
    user_id = await _get_current_user(request)
    if user_id is not None:
        return await feedback_repo.upsert(
            run_id=run_id,
            thread_id=thread_id,
            rating=body.rating,
            user_id=user_id,
            comment=body.comment,
        )
    existing = await feedback_repo.list_by_run(thread_id, run_id, limit=100, user_id=None)
    for item in existing:
        feedback_id = item.get("feedback_id")
        if isinstance(feedback_id, str):
            await feedback_repo.delete(feedback_id)
    return await _create_feedback(thread_id, run_id, body, request)


@router.post("/{thread_id}/runs/{run_id}/feedback", response_model=FeedbackResponse)
async def create_feedback(
    thread_id: str,
    run_id: str,
    body: FeedbackCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Submit feedback for a run."""
    return await _create_feedback(thread_id, run_id, body, request)


@router.get("/{thread_id}/runs/{run_id}/feedback", response_model=list[FeedbackResponse])
async def list_feedback(
    thread_id: str,
    run_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    """List all feedback for a run."""
    feedback_repo = get_feedback_repository(request)
    user_id = await _get_current_user(request)
    return await feedback_repo.list_by_run(thread_id, run_id, user_id=user_id)


@router.get("/{thread_id}/runs/{run_id}/feedback/stats", response_model=FeedbackStatsResponse)
async def feedback_stats(
    thread_id: str,
    run_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get aggregated feedback stats for a run."""
    feedback_repo = get_feedback_repository(request)
    return await feedback_repo.aggregate_by_run(thread_id, run_id)


@router.delete("/{thread_id}/runs/{run_id}/feedback")
async def delete_run_feedback(
    thread_id: str,
    run_id: str,
    request: Request,
) -> dict[str, bool]:
    """Delete all feedback records for a run."""
    feedback_repo = get_feedback_repository(request)
    user_id = await _get_current_user(request)
    if user_id is not None:
        return {"success": await feedback_repo.delete_by_run(thread_id=thread_id, run_id=run_id, user_id=user_id)}
    existing = await feedback_repo.list_by_run(thread_id, run_id, limit=100, user_id=None)
    for item in existing:
        feedback_id = item.get("feedback_id")
        if isinstance(feedback_id, str):
            await feedback_repo.delete(feedback_id)
    return {"success": True}


@router.delete("/{thread_id}/runs/{run_id}/feedback/{feedback_id}")
async def delete_feedback(
    thread_id: str,
    run_id: str,
    feedback_id: str,
    request: Request,
) -> dict[str, bool]:
    """Delete a single feedback record."""
    feedback_repo = get_feedback_repository(request)
    existing = await feedback_repo.get(feedback_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found")
    if existing.get("thread_id") != thread_id or existing.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found in run {run_id}")
    deleted = await feedback_repo.delete(feedback_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found")
    return {"success": True}
