"""Stateless runs endpoints -- stream and wait without a pre-existing thread.

These endpoints auto-create a temporary thread when no ``thread_id`` is
supplied in the request body.  When a ``thread_id`` **is** provided, it
is reused so that conversation history is preserved across calls.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.gateway.deps import get_checkpointer, get_run_manager, get_stream_bridge
from app.gateway.routers.thread_runs import RunCreateRequest
from app.gateway.services import sse_consumer, start_run
from deerflow.runtime import serialize_channel_values

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])


def _resolve_thread_id(body: RunCreateRequest) -> str:
    """Return the thread_id from the request body, or generate a new one."""
    thread_id = (body.config or {}).get("configurable", {}).get("thread_id")
    if thread_id:
        return str(thread_id)
    return str(uuid.uuid4())


@router.post("/stream")
async def stateless_stream(body: RunCreateRequest, request: Request) -> StreamingResponse:
    """Create a run and stream events via SSE.

    If ``config.configurable.thread_id`` is provided, the run is created
    on the given thread so that conversation history is preserved.
    Otherwise a new temporary thread is created.
    """
    thread_id = _resolve_thread_id(body)
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    record = await start_run(body, thread_id, request)

    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/api/threads/{thread_id}/runs/{record.run_id}",
        },
    )


@router.post("/wait", response_model=dict)
async def stateless_wait(body: RunCreateRequest, request: Request) -> dict:
    """Create a run and block until completion.

    If ``config.configurable.thread_id`` is provided, the run is created
    on the given thread so that conversation history is preserved.
    Otherwise a new temporary thread is created.
    """
    thread_id = _resolve_thread_id(body)
    record = await start_run(body, thread_id, request)

    if record.task is not None:
        try:
            await record.task
        except asyncio.CancelledError:
            pass

    checkpointer = get_checkpointer(request)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        if checkpoint_tuple is not None:
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
            channel_values = checkpoint.get("channel_values", {})
            return serialize_channel_values(channel_values)
    except Exception:
        logger.exception("Failed to fetch final state for run %s", record.run_id)

    return {"status": record.status.value, "error": record.error}
