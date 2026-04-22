"""Model usage and client feedback counters (requires ``model_feedback`` in config)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_current_user
from deerflow.runtime import get_model_feedback_store, normalize_feedback_model_name

router = APIRouter(prefix="/api", tags=["models"])


async def _require_authenticated_user_id(request: Request) -> str:
    user_id = await get_current_user(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


class ModelFeedbackRowResponse(BaseModel):
    model_name: str
    call_count: int
    success_count: int
    failure_count: int
    positive_feedback_count: int
    negative_feedback_count: int
    updated_at: float | None = None


class ModelFeedbackListResponse(BaseModel):
    enabled: bool = Field(description="False when model_feedback is disabled or not configured.")
    rows: list[ModelFeedbackRowResponse]


class ModelFeedbackSubmitBody(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=256)
    sentiment: Literal["positive", "negative"]


@router.get(
    "/models/feedback",
    response_model=ModelFeedbackListResponse,
    summary="List per-model feedback and run counters",
    description="Returns aggregated run and feedback counters per model when ``model_feedback.enabled`` is true.",
)
async def list_model_feedback(user_id: str = Depends(_require_authenticated_user_id)) -> ModelFeedbackListResponse:
    _ = user_id
    store = get_model_feedback_store()
    if store is None:
        return ModelFeedbackListResponse(enabled=False, rows=[])
    data = await store.list_rows()
    return ModelFeedbackListResponse(
        enabled=True,
        rows=[
            ModelFeedbackRowResponse(
                model_name=r.model_name,
                call_count=r.call_count,
                success_count=r.success_count,
                failure_count=r.failure_count,
                positive_feedback_count=r.positive_feedback_count,
                negative_feedback_count=r.negative_feedback_count,
                updated_at=r.updated_at,
            )
            for r in data
        ],
    )


@router.post(
    "/models/feedback",
    status_code=204,
    summary="Record user feedback for a model",
    description="Increments positive or negative feedback counter for the given configured model name.",
)
async def submit_model_feedback(
        body: ModelFeedbackSubmitBody,
        user_id: str = Depends(_require_authenticated_user_id),
) -> None:
    _ = user_id
    store = get_model_feedback_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Model feedback is not enabled")
    try:
        name = normalize_feedback_model_name(body.model_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if body.sentiment == "positive":
        await store.increment(name, positive_feedback_count=1)
    else:
        await store.increment(name, negative_feedback_count=1)
