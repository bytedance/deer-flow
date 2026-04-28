"""Cron job management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.gateway.cron_scheduler import build_request_cron_scheduler
from deerflow.runtime import (
    CronJobCreate,
    CronJobNotFoundError,
    CronJobRecord,
    CronJobUpdate,
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    update_cron_job,
)

router = APIRouter(prefix="/api/cron/jobs", tags=["cron"])


class CronTriggerResponse(BaseModel):
    """Response payload for a manual cron trigger."""

    run_id: str
    thread_id: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def _maybe_wake_scheduler(request: Request) -> None:
    scheduler = getattr(request.app.state, "cron_scheduler", None)
    if scheduler is not None:
        scheduler.wake()


@router.post("", response_model=CronJobRecord)
async def create_job(body: CronJobCreate, request: Request) -> CronJobRecord:
    """Create a persisted cron job."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Cron scheduler store not available")

    record = await create_cron_job(store, body)
    _maybe_wake_scheduler(request)
    return record


@router.get("", response_model=list[CronJobRecord])
async def list_jobs(
    request: Request,
    thread_id: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[CronJobRecord]:
    """List persisted cron jobs."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Cron scheduler store not available")
    return await list_cron_jobs(store, thread_id=thread_id, enabled=enabled, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=CronJobRecord)
async def get_job(job_id: str, request: Request) -> CronJobRecord:
    """Get a single cron job."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Cron scheduler store not available")

    record = await get_cron_job(store, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Cron job {job_id} not found")
    return record


@router.patch("/{job_id}", response_model=CronJobRecord)
async def patch_job(job_id: str, body: CronJobUpdate, request: Request) -> CronJobRecord:
    """Update a cron job."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Cron scheduler store not available")

    try:
        record = await update_cron_job(store, job_id, body)
    except CronJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Cron job {job_id} not found") from exc

    _maybe_wake_scheduler(request)
    return record


@router.delete("/{job_id}", status_code=204, response_model=None)
async def remove_job(job_id: str, request: Request) -> Response:
    """Delete a cron job."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Cron scheduler store not available")

    deleted = await delete_cron_job(store, job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Cron job {job_id} not found")

    _maybe_wake_scheduler(request)
    return Response(status_code=204)


@router.post("/{job_id}/trigger", response_model=CronTriggerResponse)
async def trigger_job(job_id: str, request: Request) -> CronTriggerResponse:
    """Trigger a cron job immediately without waiting for wall-clock dispatch."""
    scheduler = build_request_cron_scheduler(request)

    try:
        record = await scheduler.trigger_job(job_id)
    except CronJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Cron job {job_id} not found") from exc

    return CronTriggerResponse(
        run_id=record.run_id,
        thread_id=record.thread_id,
        status=record.status.value,
        metadata=record.metadata,
    )
