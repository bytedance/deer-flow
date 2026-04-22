"""LangGraph-compatible runs endpoints backed by RunsFacade."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.plugins.auth.security.actor_context import bind_request_actor_context
from app.gateway.services.runs.facade_factory import build_runs_facade_from_request
from app.gateway.services.runs.input import (
    AdaptedRunRequest,
    RunSpecBuilder,
    UnsupportedRunFeatureError,
    adapt_create_run_request,
    adapt_create_stream_request,
    adapt_create_wait_request,
    adapt_join_stream_request,
    adapt_join_wait_request,
)
from deerflow.runtime.runs.types import RunRecord, RunSpec
from deerflow.runtime.stream_bridge import JSONValue, StreamEvent

router = APIRouter(tags=["runs"])


class RunCreateRequest(BaseModel):
    assistant_id: str | None = Field(default=None, description="Agent / assistant to use")
    follow_up_to_run_id: str | None = Field(default=None, description="Lineage link to the prior run")
    input: dict[str, JSONValue] | None = Field(default=None, description="Graph input (e.g. {messages: [...]})")
    command: dict[str, JSONValue] | None = Field(default=None, description="LangGraph Command")
    metadata: dict[str, JSONValue] | None = Field(default=None, description="Run metadata")
    config: dict[str, JSONValue] | None = Field(default=None, description="RunnableConfig overrides")
    context: dict[str, JSONValue] | None = Field(default=None, description="DeerFlow context overrides (model_name, thinking_enabled, etc.)")
    webhook: str | None = Field(default=None, description="Completion callback URL")
    checkpoint_id: str | None = Field(default=None, description="Resume from checkpoint")
    checkpoint: dict[str, JSONValue] | None = Field(default=None, description="Full checkpoint object")
    interrupt_before: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt before")
    interrupt_after: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt after")
    stream_mode: list[str] | str | None = Field(default=None, description="Stream mode(s)")
    stream_subgraphs: bool = Field(default=False, description="Include subgraph events")
    stream_resumable: bool | None = Field(default=None, description="SSE resumable mode")
    on_disconnect: Literal["cancel", "continue"] = Field(default="cancel", description="Behaviour on SSE disconnect")
    on_completion: Literal["delete", "keep"] = Field(default="keep", description="Delete temp thread on completion")
    multitask_strategy: Literal["reject", "rollback", "interrupt", "enqueue"] = Field(default="reject", description="Concurrency strategy")
    after_seconds: float | None = Field(default=None, description="Delayed execution")
    if_not_exists: Literal["reject", "create"] = Field(default="create", description="Thread creation policy")
    feedback_keys: list[str] | None = Field(default=None, description="LangSmith feedback keys")


class RunResponse(BaseModel):
    run_id: str
    thread_id: str
    assistant_id: str | None = None
    status: str
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    multitask_strategy: str = "reject"
    created_at: str = ""
    updated_at: str = ""


class RunDeleteResponse(BaseModel):
    deleted: bool


class RunMessageResponse(BaseModel):
    run_id: str
    content: JSONValue
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    created_at: str
    seq: int


class RunMessagesResponse(BaseModel):
    data: list[RunMessageResponse]
    hasMore: bool = False


def format_sse(event: str, data: JSONValue, *, event_id: str | None = None) -> str:
    """Format a single SSE frame."""
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


def _record_to_response(record: RunRecord) -> RunResponse:
    return RunResponse(
        run_id=record.run_id,
        thread_id=record.thread_id,
        assistant_id=record.assistant_id,
        status=record.status,
        metadata=record.metadata,
        multitask_strategy=record.multitask_strategy,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _trim_paginated_rows(
    rows: list[dict],
    *,
    limit: int,
    after_seq: int | None,
) -> tuple[list[dict], bool]:
    has_more = len(rows) > limit
    if not has_more:
        return rows, False
    if after_seq is not None:
        return rows[:limit], True
    return rows[-limit:], True


def _event_to_run_message(event: dict) -> RunMessageResponse:
    return RunMessageResponse(
        run_id=str(event["run_id"]),
        content=event.get("content"),
        metadata=dict(event.get("metadata") or {}),
        created_at=str(event.get("created_at") or ""),
        seq=int(event["seq"]),
    )


async def _sse_consumer(
    stream: AsyncIterator[StreamEvent],
    request: Request,
    *,
    cancel_on_disconnect: bool,
    cancel_run,
    run_id: str,
) -> AsyncIterator[str]:
    try:
        async for event in stream:
            if await request.is_disconnected():
                break

            if event.event == "__heartbeat__":
                yield ": heartbeat\n\n"
                continue

            if event.event == "__end__":
                yield format_sse("end", None, event_id=event.id or None)
                return

            if event.event == "__cancelled__":
                yield format_sse("cancel", None, event_id=event.id or None)
                return

            yield format_sse(event.event, event.data, event_id=event.id or None)
    finally:
        if cancel_on_disconnect:
            await cancel_run(run_id)


def _get_run_event_store(request: Request):
    event_store = getattr(request.app.state, "run_event_store", None)
    if event_store is None:
        raise HTTPException(status_code=503, detail="Run event store not available")
    return event_store


@router.get("/{thread_id}/runs", response_model=list[RunResponse])
async def list_runs(
    thread_id: str,
    request: Request,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
) -> list[RunResponse]:
    # Accepted for API compatibility; field projection is not implemented yet.
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        records = await facade.list_runs(thread_id)
    if status is not None:
        records = [record for record in records if record.status == status]
    records = records[offset : offset + limit]
    return [_record_to_response(record) for record in records]


@router.get("/{thread_id}/runs/{run_id}", response_model=RunResponse)
async def get_run(thread_id: str, run_id: str, request: Request) -> RunResponse:
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.get_run(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _record_to_response(record)


@router.get("/{thread_id}/runs/{run_id}/messages", response_model=RunMessagesResponse)
async def run_messages(
    thread_id: str,
    run_id: str,
    request: Request,
    limit: int = 50,
    before_seq: int | None = None,
    after_seq: int | None = None,
) -> RunMessagesResponse:
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.get_run(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    event_store = _get_run_event_store(request)
    with bind_request_actor_context(request):
        rows = await event_store.list_messages_by_run(
            thread_id,
            run_id,
            limit=limit + 1,
            before_seq=before_seq,
            after_seq=after_seq,
        )
    page, has_more = _trim_paginated_rows(rows, limit=limit, after_seq=after_seq)
    return RunMessagesResponse(data=[_event_to_run_message(row) for row in page], hasMore=has_more)


def _build_spec(
    *,
    adapted: AdaptedRunRequest,
) -> RunSpec:
    try:
        return RunSpecBuilder().build(adapted)
    except UnsupportedRunFeatureError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post("/{thread_id}/runs", response_model=RunResponse)
async def create_run(
    thread_id: str,
    body: RunCreateRequest,
    request: Request,
) -> Response:
    adapted = adapt_create_run_request(
        thread_id=thread_id,
        body=body.model_dump(),
        headers=dict(request.headers),
        query=dict(request.query_params),
    )
    spec = _build_spec(adapted=adapted)
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.create_background(spec)
    return Response(
        content=_record_to_response(record).model_dump_json(),
        media_type="application/json",
        headers={"Content-Location": f"/api/threads/{thread_id}/runs/{record.run_id}"},
    )


@router.post("/{thread_id}/runs/stream")
async def stream_run(
    thread_id: str,
    body: RunCreateRequest,
    request: Request,
) -> StreamingResponse:
    adapted = adapt_create_stream_request(
        thread_id=thread_id,
        body=body.model_dump(),
        headers=dict(request.headers),
        query=dict(request.query_params),
    )

    spec = _build_spec(adapted=adapted)

    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record, stream = await facade.create_and_stream(spec)

    return StreamingResponse(
        _sse_consumer(
            stream,
            request,
            cancel_on_disconnect=spec.on_disconnect == "cancel",
            cancel_run=facade.cancel,
            run_id=record.run_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/api/threads/{thread_id}/runs/{record.run_id}",
        },
    )


@router.post("/{thread_id}/runs/wait")
async def wait_run(
    thread_id: str,
    body: RunCreateRequest,
    request: Request,
) -> Response:
    adapted = adapt_create_wait_request(
        thread_id=thread_id,
        body=body.model_dump(),
        headers=dict(request.headers),
        query=dict(request.query_params),
    )
    spec = _build_spec(adapted=adapted)
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record, result = await facade.create_and_wait(spec)
    return Response(
        content=json.dumps(result, default=str, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Location": f"/api/threads/{thread_id}/runs/{record.run_id}"},
    )


@router.post("/runs", response_model=RunResponse)
async def create_stateless_run(body: RunCreateRequest, request: Request) -> Response:
    adapted = adapt_create_run_request(
        thread_id=None,
        body=body.model_dump(),
        headers=dict(request.headers),
        query=dict(request.query_params),
    )
    spec = _build_spec(adapted=adapted)
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.create_background(spec)
    return Response(
        content=_record_to_response(record).model_dump_json(),
        media_type="application/json",
        headers={"Content-Location": f"/api/threads/{record.thread_id}/runs/{record.run_id}"},
    )


@router.post("/runs/stream")
async def create_stateless_stream_run(body: RunCreateRequest, request: Request) -> StreamingResponse:
    adapted = adapt_create_stream_request(
        thread_id=None,
        body=body.model_dump(),
        headers=dict(request.headers),
        query=dict(request.query_params),
    )
    spec = _build_spec(adapted=adapted)
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record, stream = await facade.create_and_stream(spec)

    return StreamingResponse(
        _sse_consumer(
            stream,
            request,
            cancel_on_disconnect=spec.on_disconnect == "cancel",
            cancel_run=facade.cancel,
            run_id=record.run_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/api/threads/{record.thread_id}/runs/{record.run_id}",
        },
    )


@router.post("/runs/wait")
async def wait_stateless_run(body: RunCreateRequest, request: Request) -> Response:
    adapted = adapt_create_wait_request(
        thread_id=None,
        body=body.model_dump(),
        headers=dict(request.headers),
        query=dict(request.query_params),
    )
    spec = _build_spec(adapted=adapted)
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record, result = await facade.create_and_wait(spec)
    return Response(
        content=json.dumps(result, default=str, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Location": f"/api/threads/{record.thread_id}/runs/{record.run_id}"},
    )


@router.api_route("/{thread_id}/runs/{run_id}/stream", methods=["GET", "POST"], response_model=None)
async def stream_existing_run(
    thread_id: str,
    run_id: str,
    request: Request,
    action: Literal["interrupt", "rollback"] | None = None,
    wait: bool = False,
    cancel_on_disconnect: bool = False,
    stream_mode: str | None = None,
) -> StreamingResponse | Response:
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.get_run(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if action is not None:
        with bind_request_actor_context(request):
            cancelled = await facade.cancel(run_id, action=action)
        if not cancelled:
            raise HTTPException(status_code=409, detail=f"Run {run_id} is not cancellable")
        if wait:
            with bind_request_actor_context(request):
                await facade.join_wait(run_id)
            return Response(status_code=204)

    adapted = adapt_join_stream_request(
        thread_id=thread_id,
        run_id=run_id,
        headers=dict(request.headers),
        query=dict(request.query_params),
    )
    with bind_request_actor_context(request):
        stream = await facade.join_stream(run_id, last_event_id=adapted.last_event_id)

    return StreamingResponse(
        _sse_consumer(
            stream,
            request,
            cancel_on_disconnect=cancel_on_disconnect,
            cancel_run=facade.cancel,
            run_id=run_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{thread_id}/runs/{run_id}/join")
async def join_existing_run(
    thread_id: str,
    run_id: str,
    request: Request,
    cancel_on_disconnect: bool = False,
) -> JSONValue:
    # Accepted for API compatibility; current join_wait path does not change
    # behavior based on client disconnect.
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.get_run(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    adapted = adapt_join_wait_request(
        thread_id=thread_id,
        run_id=run_id,
        headers=dict(request.headers),
        query=dict(request.query_params),
    )
    with bind_request_actor_context(request):
        return await facade.join_wait(run_id, last_event_id=adapted.last_event_id)


@router.post("/{thread_id}/runs/{run_id}/cancel")
async def cancel_existing_run(
    thread_id: str,
    run_id: str,
    request: Request,
    wait: bool = False,
    action: Literal["interrupt", "rollback"] = "interrupt",
) -> JSONValue:
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.get_run(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    with bind_request_actor_context(request):
        cancelled = await facade.cancel(run_id, action=action)
    if not cancelled:
        raise HTTPException(status_code=409, detail=f"Run {run_id} is not cancellable")
    if wait:
        with bind_request_actor_context(request):
            return await facade.join_wait(run_id)
    return {}


@router.delete("/{thread_id}/runs/{run_id}", response_model=RunDeleteResponse)
async def delete_run(
    thread_id: str,
    run_id: str,
    request: Request,
) -> RunDeleteResponse:
    facade = build_runs_facade_from_request(request)
    with bind_request_actor_context(request):
        record = await facade.get_run(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    with bind_request_actor_context(request):
        deleted = await facade.delete_run(run_id)
    return RunDeleteResponse(deleted=deleted)
