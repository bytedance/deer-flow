"""Feedback API router — submit and query user feedback."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.auth.dependencies import require_admin
from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user, get_feedback_repo, get_run_store
from deerflow.config.tenant import get_current_tenant_id
from deerflow.feedback.storage import FeedbackEntry, FeedbackStorage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple feedback (legacy / non-run-scoped)
# ---------------------------------------------------------------------------

simple_feedback_router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class SubmitFeedbackRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID")
    message_id: str = Field(..., description="Message ID")
    rating: int = Field(..., ge=1, le=5, description="Rating 1-5")
    categories: list[str] = Field(default_factory=list, description="Feedback categories")
    comment: str = Field(default="", description="Optional text comment")


class FeedbackSummaryResponse(BaseModel):
    total_feedback: int
    avg_rating: float
    rating_distribution: dict[str, int]
    top_categories: list[dict]


@simple_feedback_router.post("")
async def submit_feedback(req: SubmitFeedbackRequest, request: Request) -> dict:
    """Submit user feedback for an AI response."""
    tenant_id = get_current_tenant_id()
    entry = FeedbackEntry(
        id=uuid.uuid4().hex[:12],
        tenant_id=tenant_id,
        thread_id=req.thread_id,
        message_id=req.message_id,
        rating=req.rating,
        categories=req.categories,
        comment=req.comment,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    storage = FeedbackStorage()
    storage.add(entry)
    return {"success": True, "id": entry.id}


@simple_feedback_router.get("/summary", response_model=FeedbackSummaryResponse)
async def get_feedback_summary(
    start_date: str | None = Query(default=None, description="Start date (ISO format)"),
    end_date: str | None = Query(default=None, description="End date (ISO format)"),
    tenant_id: str | None = Query(default=None, description="Filter by tenant ID"),
    user=Depends(require_admin),
) -> FeedbackSummaryResponse:
    """Get aggregated feedback summary (admin only)."""
    summary = FeedbackStorage.get_cross_tenant_summary(
        start_date=start_date, end_date=end_date, tenant_id=tenant_id,
    )
    return FeedbackSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# Run-scoped feedback endpoints
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/threads", tags=["feedback"])


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


@router.put("/{thread_id}/runs/{run_id}/feedback", response_model=FeedbackResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def upsert_feedback(
    thread_id: str,
    run_id: str,
    body: FeedbackUpsertRequest,
    request: Request,
) -> dict[str, Any]:
    """Create or update feedback for a run (idempotent)."""
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be +1 or -1")

    user_id = await get_current_user(request)

    run_store = get_run_store(request)
    run = await run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.get("thread_id") != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in thread {thread_id}")

    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.upsert(
        run_id=run_id,
        thread_id=thread_id,
        rating=body.rating,
        user_id=user_id,
        comment=body.comment,
    )


@router.delete("/{thread_id}/runs/{run_id}/feedback")
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_run_feedback(
    thread_id: str,
    run_id: str,
    request: Request,
) -> dict[str, bool]:
    """Delete the current user's feedback for a run."""
    user_id = await get_current_user(request)
    feedback_repo = get_feedback_repo(request)
    deleted = await feedback_repo.delete_by_run(
        thread_id=thread_id,
        run_id=run_id,
        user_id=user_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="No feedback found for this run")
    return {"success": True}


@router.post("/{thread_id}/runs/{run_id}/feedback", response_model=FeedbackResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def create_feedback(
    thread_id: str,
    run_id: str,
    body: FeedbackCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Submit feedback (thumbs-up/down) for a run."""
    if body.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be +1 or -1")

    user_id = await get_current_user(request)

    run_store = get_run_store(request)
    run = await run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.get("thread_id") != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in thread {thread_id}")

    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.create(
        run_id=run_id,
        thread_id=thread_id,
        rating=body.rating,
        user_id=user_id,
        message_id=body.message_id,
        comment=body.comment,
    )


@router.get("/{thread_id}/runs/{run_id}/feedback", response_model=list[FeedbackResponse])
@require_permission("threads", "read", owner_check=True)
async def list_feedback(
    thread_id: str,
    run_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    """List all feedback for a run."""
    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.list_by_run(thread_id, run_id)


@router.get("/{thread_id}/runs/{run_id}/feedback/stats", response_model=FeedbackStatsResponse)
@require_permission("threads", "read", owner_check=True)
async def feedback_stats(
    thread_id: str,
    run_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get aggregated feedback stats (positive/negative counts) for a run."""
    feedback_repo = get_feedback_repo(request)
    return await feedback_repo.aggregate_by_run(thread_id, run_id)


@router.delete("/{thread_id}/runs/{run_id}/feedback/{feedback_id}")
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_feedback(
    thread_id: str,
    run_id: str,
    feedback_id: str,
    request: Request,
) -> dict[str, bool]:
    """Delete a feedback record."""
    feedback_repo = get_feedback_repo(request)
    existing = await feedback_repo.get(feedback_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found")
    if existing.get("thread_id") != thread_id or existing.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found in run {run_id}")
    deleted = await feedback_repo.delete(feedback_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found")
    return {"success": True}
