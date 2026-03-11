"""API router for cron job management."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from src.cron import get_cron_service
from src.cron.service import NoFutureRunTimeError
from src.cron.types import CronPayload, CronSchedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cron", tags=["cron"])


def _job_to_response(job: dict) -> dict:
    """Convert a job dict to API response format."""
    next_run = job.get("state", {}).get("next_run_at_ms")
    last_run = job.get("state", {}).get("last_run_at_ms")

    return {
        "id": job["id"],
        "name": job["name"],
        "enabled": job["enabled"],
        "schedule": job["schedule"],
        "payload": job["payload"],
        "state": {
            "next_run_at": datetime.fromtimestamp(next_run / 1000).isoformat() if next_run else None,
            "last_run_at": datetime.fromtimestamp(last_run / 1000).isoformat() if last_run else None,
            "last_status": job.get("state", {}).get("last_status", "pending"),
            "last_error": job.get("state", {}).get("last_error"),
        },
        "delete_after_run": job.get("delete_after_run", False),
        "created_at": datetime.fromtimestamp(job.get("created_at_ms", 0) / 1000).isoformat(),
    }


@router.get("")
async def list_jobs(include_disabled: bool = True) -> list[dict]:
    """List all scheduled cron jobs."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    jobs = cron_service.list_jobs(include_disabled=include_disabled)
    return [_job_to_response(job) for job in jobs]


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Get cron service status."""
    cron_service = get_cron_service()
    if cron_service is None:
        return {"running": False, "jobs": 0, "enabled": 0, "disabled": 0}

    return cron_service.status()


@router.post("")
async def add_job(request: dict) -> dict:
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
        schedule_data = request.get("schedule", {})
        payload_data = request.get("payload", {})

        schedule = CronSchedule(
            kind=schedule_data.get("kind", "at"),
            at_ms=schedule_data.get("at_ms"),
            every_ms=schedule_data.get("every_ms"),
            expr=schedule_data.get("expr"),
            tz=schedule_data.get("tz"),
        )

        payload = CronPayload(
            kind=payload_data.get("kind", "agent_turn"),
            message=payload_data.get("message", ""),
            deliver=payload_data.get("deliver", False),
            channel=payload_data.get("channel"),
            to=payload_data.get("to"),
            thread_ts=payload_data.get("thread_ts"),
            thread_id=payload_data.get("thread_id"),
            assistant_id=payload_data.get("assistant_id"),
            agent_name=payload_data.get("agent_name"),
            thinking_enabled=payload_data.get("thinking_enabled"),
            subagent_enabled=payload_data.get("subagent_enabled"),
        )

        job = cron_service.add_job(
            name=request.get("name", "Untitled"),
            schedule=schedule,
            payload=payload,
            enabled=request.get("enabled", True),
            delete_after_run=request.get("delete_after_run", False),
        )

        return _job_to_response(job.to_dict())

    except Exception as e:
        logger.error(f"Failed to add cron job: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{job_id}")
async def remove_job(job_id: str) -> dict:
    """Remove a cron job by ID."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    if cron_service.remove_job(job_id):
        return {"status": "removed", "job_id": job_id}

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.post("/{job_id}/enable")
async def enable_job(job_id: str) -> dict:
    """Enable a cron job."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    try:
        if cron_service.enable_job(job_id, enabled=True):
            return {"status": "enabled", "job_id": job_id}
    except NoFutureRunTimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.post("/{job_id}/disable")
async def disable_job(job_id: str) -> dict:
    """Disable a cron job."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    if cron_service.enable_job(job_id, enabled=False):
        return {"status": "disabled", "job_id": job_id}

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.post("/{job_id}/run")
async def run_job(job_id: str) -> dict:
    """Manually trigger a cron job."""
    cron_service = get_cron_service()
    if cron_service is None:
        raise HTTPException(status_code=503, detail="Cron service is not running")

    result = await cron_service.run_job(job_id, force=True)
    if result is not None:
        return {"status": "executed", "job_id": job_id, "result": result}

    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
