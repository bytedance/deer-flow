"""GenUI interaction API router — handles UI block interaction submissions."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_run_context, get_run_manager, get_stream_bridge
from app.gateway.services import build_run_config, resolve_agent_factory
from deerflow.agents.middlewares.genui_middleware import (
    get_interaction_store,
    process_interaction,
)
from deerflow.runtime import DisconnectMode, run_agent

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

    Validates the callback, checks expiry and idempotency,
    then resumes the agent graph with the interaction as a HumanMessage.
    """
    store = get_interaction_store()
    record = store.get(req.callback_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown callback: {req.callback_id}")

    if record.thread_id != thread_id:
        raise HTTPException(status_code=400, detail="Callback does not belong to this thread")

    try:
        human_message = process_interaction(req.callback_id, req.payload)
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
        "UI interaction submitted, resuming graph: callback=%s thread=%s",
        req.callback_id,
        thread_id,
    )

    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    agent_factory = resolve_agent_factory(None)
    config = build_run_config(thread_id, None, None)
    graph_input = {"messages": [human_message]}

    try:
        run_record = await run_mgr.create_or_reject(
            thread_id,
            None,
            on_disconnect=DisconnectMode.continue_,
            metadata={"source": "ui_interaction", "callback_id": req.callback_id},
            kwargs={"input": graph_input, "config": config},
            multitask_strategy="reject",
        )
    except Exception as exc:
        logger.warning("Failed to create run for interaction resumption: %s", exc)
        return UIInteractionResponse(
            success=True,
            message="Interaction received (graph busy)",
            callback_id=req.callback_id,
        )

    task = asyncio.create_task(
        run_agent(
            bridge,
            run_mgr,
            run_record,
            ctx=run_ctx,
            agent_factory=agent_factory,
            graph_input=graph_input,
            config=config,
            stream_modes=["values", "messages", "custom"],
            stream_subgraphs=False,
        )
    )
    run_record.task = task

    return UIInteractionResponse(
        success=True,
        message="Interaction submitted",
        callback_id=req.callback_id,
    )
