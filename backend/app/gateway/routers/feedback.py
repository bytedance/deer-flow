"""Feedback API router — submit and query user feedback."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.auth.dependencies import require_admin
from deerflow.config.tenant import get_current_tenant_id
from deerflow.feedback.storage import FeedbackEntry, FeedbackStorage

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


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


@router.post("")
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


@router.get("/summary", response_model=FeedbackSummaryResponse)
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
