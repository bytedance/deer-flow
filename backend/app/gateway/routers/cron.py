"""API router for cron job management."""

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from src.cron import get_cron_service
from src.cron.service import NoFutureRunTimeError
from src.cron.types import CronPayload, CronSchedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cron", tags=["cron"])


class CronScheduleRequest(BaseModel):
    """Request model for cron schedule configuration."""

    kind: Literal["at", "every", "cron"] = Field(..., description="Schedule kind")
    at_ms: int | None = Field(default=None, description="Unix timestamp in milliseconds for one-time jobs")
    every_ms: int | None = Field(default=None, gt=0, description="Recurring interval in milliseconds")
    expr: str | None = Field(default=None, description="Cron expression for cron schedules")
    tz: str | None = Field(default=None, description="Optional timezone for cron schedules")

    @model_validator(mode="after")
    def validate_schedule_fields(self) -> "CronScheduleRequest":
        """Validate required fields for the selected schedule kind."""
        if self.tz and self.kind != "cron":
            raise ValueError("timezone can only be used with cron schedules")

        if self.kind == "at" and self.at_ms is None:
            raise ValueError("at schedules require 'at_ms'")

        if self.kind == "every" and self.every_ms is None:
            raise ValueError("every schedules require a positive 'every_ms'")

        if self.kind == "cron" and not self.expr:
            raise ValueError("cron schedules require 'expr'")

        return self


class CronPayloadRequest(BaseModel):
    """Request model for cron job payload."""

    kind: Literal["agent_turn", "system_event"] = Field(default="agent_turn", description="Payload kind")
    message: str = Field(default="", description="Task description or scheduled prompt")
    deliver: bool = Field(default=False, description="Whether to deliver results to an IM channel")
    channel: str | None = Field(default=None, description="Target channel name")
    to: str | None = Field(default=None, description="Target chat or user id")
    thread_ts: str | None = Field(default=None, description="Optional channel thread identifier")
    thread_id: str | None = Field(default=None, description="Optional DeerFlow thread id")
    assistant_id: str | None = Field(default=None, description="Optional assistant id override")
    agent_name: str | None = Field(default=None, description="Optional custom agent name override")
    thinking_enabled: bool | None = Field(default=None, description="Optional thinking mode override")
    subagent_enabled: bool | None = Field(default=None, description="Optional subagent mode override")


class AddCronJobRequest(BaseModel):
    """Request model for creating a cron job."""

    name: str = Field(default="Untitled", description="Human-readable job name")
    schedule: CronScheduleRequest = Field(..., description="When the cron job should run")
    payload: CronPayloadRequest = Field(default_factory=CronPayloadRequest, description="Job execution payload")
    enabled: bool = Field(default=True, description="Whether the job starts enabled")
    delete_after_run: bool = Field(default=False, description="Delete one-time jobs after a successful run")


class CronScheduleResponse(BaseModel):
    """Response model for cron schedule configuration."""

    kind: Literal["at", "every", "cron"]
    at_ms: int | None = None
    every_ms: int | None = None
    expr: str | None = None
    tz: str | None = None


class CronPayloadResponse(BaseModel):
    """Response model for cron payload configuration."""

    kind: Literal["agent_turn", "system_event"] = "agent_turn"
    message: str = ""
    deliver: bool = False
    channel: str | None = None
    to: str | None = None
    thread_ts: str | None = None
    thread_id: str | None = None
    assistant_id: str | None = None
    agent_name: str | None = None
    thinking_enabled: bool | None = None
    subagent_enabled: bool | None = None


class CronJobStateResponse(BaseModel):
    """Response model for cron job runtime state."""

    next_run_at: str | None = Field(default=None, description="ISO timestamp of the next scheduled run")
    last_run_at: str | None = Field(default=None, description="ISO timestamp of the last completed run")
    last_status: Literal["pending", "ok", "error"] = Field(default="pending", description="Last execution status")
    last_error: str | None = Field(default=None, description="Last execution error, if any")


class CronJobResponse(BaseModel):
    """Response model for a cron job."""

    id: str = Field(..., description="Cron job id")
    name: str = Field(..., description="Human-readable job name")
    enabled: bool = Field(..., description="Whether the job is currently enabled")
    schedule: CronScheduleResponse = Field(..., description="Schedule definition")
    payload: CronPayloadResponse = Field(..., description="Execution payload")
    state: CronJobStateResponse = Field(..., description="Runtime status fields")
    delete_after_run: bool = Field(default=False, description="Delete one-time jobs after a successful run")
    created_at: str = Field(..., description="ISO timestamp when the job was created")


class CronStatusResponse(BaseModel):
    """Response model for cron service status."""

    running: bool
    jobs: int
    enabled: int
    disabled: int


class CronJobActionResponse(BaseModel):
    """Response model for enable/disable/remove operations."""

    status: str
    job_id: str


class CronJobRunResponse(CronJobActionResponse):
    """Response model for manual job execution."""

    result: str


def _job_to_response(job: dict) -> CronJobResponse:
    """Convert a job dict to API response format."""
    job_state = job.get("state", {})
    next_run = job_state.get("next_run_at_ms")
    last_run = job_state.get("last_run_at_ms")
    created_at_ms = job.get("created_at_ms", 0)

    def _isoformat_ms(timestamp_ms: int | None) -> str | None:
        if timestamp_ms is None:
            return None
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()

    return CronJobResponse(
        id=job["id"],
        name=job["name"],
        enabled=job["enabled"],
        schedule=CronScheduleResponse(**job["schedule"]),
        payload=CronPayloadResponse(**job["payload"]),
        state=CronJobStateResponse(
            next_run_at=_isoformat_ms(next_run),
            last_run_at=_isoformat_ms(last_run),
            last_status=job_state.get("last_status", "pending"),
            last_error=job_state.get("last_error"),
        ),
        delete_after_run=job.get("delete_after_run", False),
        created_at=_isoformat_ms(created_at_ms) or datetime.fromtimestamp(0, tz=UTC).isoformat(),
    )


@router.get("", response_model=list[CronJobResponse])
async def list_jobs(include_disabled: bool = True) -> list[CronJobResponse]:
    """List all scheduled cron jobs."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    jobs = await cron_service.list_jobs(include_disabled=include_disabled)
    return [_job_to_response(job) for job in jobs]


@router.get("/status", response_model=CronStatusResponse)
async def get_status() -> CronStatusResponse:
    """Get cron service status."""
    cron_service = get_cron_service()
    if cron_service is None:
        return CronStatusResponse(running=False, jobs=0, enabled=0, disabled=0)

    return CronStatusResponse(**(await cron_service.status()))


@router.post("", response_model=CronJobResponse)
async def add_job(request: AddCronJobRequest) -> CronJobResponse:
    """Add a new cron job.

    Request body:
    {
        "name": "Job name",
        "schedule": {
            "kind": "at" | "every" | "cron",
            "at_ms": <timestamp_ms>,  // for "at"
            "every_ms": <interval_ms>,  // for "every"
            "expr": "0 9 * * *",  // for "cron"
            "tz": "Asia/Shanghai"  // optional timezone
        },
        "payload": {
            "message": "Task description",
            "deliver": true,
            "channel": "telegram",
            "to": "user_id",
            "thread_ts": "optional-thread-id",
            "agent_name": "optional-custom-agent"
        },
        "enabled": true,
        "delete_after_run": false
    }
    """
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    try:
        schedule = CronSchedule(
            kind=request.schedule.kind,
            at_ms=request.schedule.at_ms,
            every_ms=request.schedule.every_ms,
            expr=request.schedule.expr,
            tz=request.schedule.tz,
        )

        payload = CronPayload(
            kind=request.payload.kind,
            message=request.payload.message,
            deliver=request.payload.deliver,
            channel=request.payload.channel,
            to=request.payload.to,
            thread_ts=request.payload.thread_ts,
            thread_id=request.payload.thread_id,
            assistant_id=request.payload.assistant_id,
            agent_name=request.payload.agent_name,
            thinking_enabled=request.payload.thinking_enabled,
            subagent_enabled=request.payload.subagent_enabled,
        )

        job = await cron_service.add_job(
            name=request.name,
            schedule=schedule,
            payload=payload,
            enabled=request.enabled,
            delete_after_run=request.delete_after_run,
        )

        return _job_to_response(job.to_dict())

    except Exception as e:
        logger.error(f"Failed to add cron job: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{job_id}", response_model=CronJobActionResponse)
async def remove_job(job_id: str) -> CronJobActionResponse:
    """Remove a cron job by ID."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    if await cron_service.remove_job(job_id):
        return CronJobActionResponse(status="removed", job_id=job_id)

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.post("/{job_id}/enable", response_model=CronJobActionResponse)
async def enable_job(job_id: str) -> CronJobActionResponse:
    """Enable a cron job."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    try:
        if await cron_service.enable_job(job_id, enabled=True):
            return CronJobActionResponse(status="enabled", job_id=job_id)
    except NoFutureRunTimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.post("/{job_id}/disable", response_model=CronJobActionResponse)
async def disable_job(job_id: str) -> CronJobActionResponse:
    """Disable a cron job."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    if await cron_service.enable_job(job_id, enabled=False):
        return CronJobActionResponse(status="disabled", job_id=job_id)

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.post("/{job_id}/run", response_model=CronJobRunResponse)
async def run_job(job_id: str) -> CronJobRunResponse:
    """Manually trigger a cron job."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    result = await cron_service.run_job(job_id, force=True)
    if result is not None:
        return CronJobRunResponse(status="executed", job_id=job_id, result=result)

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
