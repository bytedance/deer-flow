"""Durable workflow runtime read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.gateway.authz import require_permission
from app.gateway.deps import get_run_event_store, get_run_store, get_workflow_store

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _workflow_timeline_event(row: dict) -> dict:
    return {
        "kind": "workflow_event",
        "seq": row.get("seq"),
        "event_type": row.get("event_type"),
        "category": row.get("category"),
        "created_at": row.get("created_at"),
        "thread_id": row.get("thread_id"),
        "run_id": row.get("run_id"),
        "checkpoint_ns": row.get("checkpoint_ns"),
        "checkpoint_id": row.get("checkpoint_id"),
        "run_event_seq": row.get("run_event_seq"),
        "content": row.get("content"),
        "metadata": row.get("metadata") or {},
    }


def _run_timeline_event(row: dict) -> dict:
    return {
        "kind": "run_event",
        "seq": row.get("seq"),
        "event_type": row.get("event_type"),
        "category": row.get("category"),
        "created_at": row.get("created_at"),
        "thread_id": row.get("thread_id"),
        "run_id": row.get("run_id"),
        "content": row.get("content"),
        "metadata": row.get("metadata") or {},
    }


def _timeline_sort_key(row: dict) -> tuple[str, int, int]:
    created_at = str(row.get("created_at") or "")
    kind_order = 0 if row.get("kind") == "workflow_event" else 1
    seq = row.get("seq")
    return created_at, kind_order, int(seq) if isinstance(seq, int) else 0


@router.get("")
@require_permission("runs", "read")
async def list_workflows(
    request: Request,
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """List durable workflow envelopes."""
    store = get_workflow_store(request)
    rows = await store.list(
        status=status,
        source_type=source_type,
        source=source,
        thread_id=thread_id,
        run_id=run_id,
        user_id=user_id,
        limit=limit,
    )
    return {"data": rows}


@router.get("/by-run/{run_id}")
@require_permission("runs", "read")
async def get_workflow_by_run(run_id: str, request: Request, thread_id: str | None = Query(default=None)) -> dict:
    """Fetch the durable workflow envelope bound to a DeerFlow run."""
    store = get_workflow_store(request)
    rows = await store.list(thread_id=thread_id, run_id=run_id, limit=2)
    if not rows:
        raise HTTPException(status_code=404, detail=f"Workflow for run {run_id} not found")
    return rows[0]


@router.get("/{workflow_id}")
@require_permission("runs", "read")
async def get_workflow(workflow_id: str, request: Request, user_id: str | None = Query(default=None)) -> dict:
    """Fetch one durable workflow envelope."""
    store = get_workflow_store(request)
    row = await store.get(workflow_id, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return row


@router.get("/{workflow_id}/events")
@require_permission("runs", "read")
async def list_workflow_events(
    workflow_id: str,
    request: Request,
    event_type: list[str] | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict:
    """List append-only lifecycle events for one workflow."""
    store = get_workflow_store(request)
    workflow = await store.get(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    rows = await store.list_events(workflow_id, event_types=event_type, limit=limit)
    return {"workflow": workflow, "events": rows}


@router.get("/{workflow_id}/timeline")
@require_permission("runs", "read")
async def get_workflow_timeline(
    workflow_id: str,
    request: Request,
    include_run_events: bool = Query(default=True),
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict:
    """Return a durable run trace merged from workflow and run events."""
    store = get_workflow_store(request)
    workflow = await store.get(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    workflow_events = await store.list_events(workflow_id, limit=limit)
    run_events: list[dict] = []
    thread_id = workflow.get("thread_id")
    run_id = workflow.get("run_id")
    if include_run_events and thread_id and run_id:
        run_event_store = get_run_event_store(request)
        run_events = await run_event_store.list_events(thread_id, run_id, limit=limit)

    run = None
    if run_id:
        run_store = get_run_store(request)
        run = await run_store.get(run_id)

    timeline = [_workflow_timeline_event(row) for row in workflow_events]
    timeline.extend(_run_timeline_event(row) for row in run_events)
    timeline.sort(key=_timeline_sort_key)

    return {
        "workflow": workflow,
        "run": run,
        "timeline": timeline[:limit],
        "workflow_events": workflow_events,
        "run_events": run_events,
    }
