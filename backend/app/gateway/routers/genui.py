"""GenUI interaction API router — handles UI block interaction submissions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deerflow.agents.middlewares.genui_middleware import (
    get_interaction_store,
    process_interaction,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/ui-interaction", tags=["genui"])


class UIInteractionRequest(BaseModel):
    callback_id: str = Field(..., description="The callback ID from the interactive UI block")
    payload: dict = Field(default_factory=dict, description="Interaction payload data")


class UIInteractionResponse(BaseModel):
    success: bool
    message: str
    callback_id: str


@router.post("", response_model=UIInteractionResponse)
async def submit_ui_interaction(
    thread_id: str,
    req: UIInteractionRequest,
    request: Request,
) -> UIInteractionResponse:
    """Submit a user interaction for an interactive UI block.

    Validates the callback, checks expiry and idempotency, and registers the
    submission. The frontend is responsible for sending the interaction payload
    as a follow-up message through the normal streaming path.
    """
    store = get_interaction_store()
    record = store.get(thread_id, req.callback_id)

    if record is None:
        # Debug: list all registered callbacks for this thread
        all_keys = [k for k in store._records.keys() if k.startswith(thread_id)]
        logger.warning(
            "Unknown callback '%s' for thread '%s'. Registered callbacks for this thread: %s",
            req.callback_id, thread_id, all_keys,
        )
        raise HTTPException(status_code=404, detail=f"Unknown callback: {req.callback_id}")

    try:
        human_message = process_interaction(thread_id, req.callback_id, req.payload)
    except TimeoutError:
        raise HTTPException(status_code=410, detail="Callback has expired")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if human_message is None:
        return UIInteractionResponse(
            success=True,
            message="Already submitted (idempotent)",
            callback_id=req.callback_id,
        )

    logger.info(
        "UI interaction registered: callback=%s thread=%s",
        req.callback_id,
        thread_id,
    )

    return UIInteractionResponse(
        success=True,
        message="Interaction submitted",
        callback_id=req.callback_id,
    )
