"""Feedback endpoints — rate a run, retract a rating.

Thumbs-up/down on a run, aligned with the mainstream chat UX: PUT is an
idempotent upsert ("my current verdict is X"), DELETE retracts it
(clicking the active button again). The current rating is echoed back to
the UI inside the message-list payload, not through a separate read
endpoint.

Primary adapter only: resolves the current user, delegates to
``FeedbackService`` (input port), and maps domain errors to HTTP codes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import FeedbackServiceDep, get_current_user
from deerflow.domain.feedback import (
    DuplicateFeedbackError,
    Feedback,
    InvalidRatingError,
    InvalidTagError,
    RateRun,
    RetractRunRating,
    RunNotFoundError,
)
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["feedback"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RateRunRequest(BaseModel):
    """Request model of the RateRun use case (name = command name + Request).

    Carries only what the client may supply: identity (user_id) never
    appears on a request model -- it is resolved server-side and injected
    through ``to_command``.
    """

    rating: int = Field(..., description="Feedback rating: +1 (positive) or -1 (negative)")
    comment: str | None = Field(default=None, description="Optional text feedback")
    tags: list[str] = Field(
        default_factory=list,
        description="Optional thumbs-down reason slugs (e.g. 'incorrect', 'slow')",
    )

    def to_command(self, thread_id: str, run_id: str, user_id: str | None) -> RateRun:
        """Body + path + resolved identity -> the use-case command.

        The wire shape owns the inbound translation into domain vocabulary
        (wire types become domain types here, e.g. list -> tuple).
        """
        return RateRun(
            thread_id=thread_id,
            run_id=run_id,
            rating=self.rating,
            user_id=user_id,
            comment=self.comment,
            tags=tuple(self.tags),
        )


class FeedbackResponse(BaseModel):
    feedback_id: str
    run_id: str
    thread_id: str
    user_id: str | None = None
    rating: int
    comment: str | None = None
    tags: list[str] = []
    created_at: str = ""

    @classmethod
    def from_domain(cls, feedback: Feedback) -> FeedbackResponse:
        """Domain object -> wire shape (allowlist). ``created_at`` keeps the
        legacy ``coerce_iso`` serialization so the API output is
        byte-identical."""
        return cls(
            feedback_id=feedback.feedback_id,
            run_id=feedback.run_id,
            thread_id=feedback.thread_id,
            user_id=feedback.user_id,
            rating=feedback.rating,
            comment=feedback.comment,
            tags=list(feedback.tags),
            created_at=coerce_iso(feedback.created_at),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.put("/{thread_id}/runs/{run_id}/feedback", response_model=FeedbackResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def upsert_feedback(
    thread_id: str,
    run_id: str,
    body: RateRunRequest,
    request: Request,
    service: FeedbackServiceDep,
) -> FeedbackResponse:
    """Set the current user's rating for a run (idempotent upsert)."""
    user_id = await get_current_user(request)
    try:
        feedback = await service.rate_run(body.to_command(thread_id, run_id, user_id))
    except InvalidRatingError:
        raise HTTPException(status_code=400, detail="rating must be +1 or -1")
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found in thread {thread_id}")
    except DuplicateFeedbackError:
        # Lost a concurrent-upsert race (legacy behavior was a 500); the
        # client can simply retry.
        raise HTTPException(status_code=409, detail="Concurrent feedback update, please retry")
    return FeedbackResponse.from_domain(feedback)


@router.delete("/{thread_id}/runs/{run_id}/feedback")
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_run_feedback(
    thread_id: str,
    run_id: str,
    request: Request,
    service: FeedbackServiceDep,
) -> dict[str, bool]:
    """Retract the current user's rating for a run."""
    user_id = await get_current_user(request)
    retracted = await service.retract_run_rating(RetractRunRating(thread_id=thread_id, run_id=run_id, user_id=user_id))
    if not retracted:
        raise HTTPException(status_code=404, detail="No feedback found for this run")
    return {"success": True}
