"""HTTP API for user-owned scheduled jobs.

Endpoints:

- ``GET    /api/scheduled_jobs``                — list caller's jobs
- ``POST   /api/scheduled_jobs``                — create a new job
- ``GET    /api/scheduled_jobs/{job_id}``       — fetch one job
- ``PATCH  /api/scheduled_jobs/{job_id}``       — edit name/description/trigger/enabled
- ``DELETE /api/scheduled_jobs/{job_id}``       — hard-delete
- ``POST   /api/scheduled_jobs/{job_id}/run``   — manual trigger (force/due)
- ``GET    /api/scheduled_jobs/{job_id}/runs``  — execution history
- ``GET    /api/scheduled_jobs/quota``          — current quota usage

All endpoints rely on ``ScheduledJobRepository`` AUTO-sentinel user-id
resolution. The repository pulls ``user_id`` from the request-scoped
ContextVar, which the auth middleware sets at request entry — so callers
cannot read or mutate another user's jobs.

Per-user quota is enforced on create: max ``MAX_ENABLED_JOBS_PER_USER``
(20) enabled jobs, and the tightest cron cadence allowed is
``MIN_CRON_INTERVAL_SECONDS`` (30 minutes).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.scheduled_job_runs import ScheduledJobRunRepository
from deerflow.persistence.scheduled_jobs import ScheduledJobRepository
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.scheduler.triggers import (
    AtTrigger,
    CronTrigger,
    EveryTrigger,
    parse_user_when,
)
from deerflow.utils.time import coerce_datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduled_jobs", tags=["scheduled-jobs"])


async def _require_user(request: Request):
    """Pull the authenticated user from request.state.

    Production auth middleware sets ``request.state.user`` and
    ``request.state.auth_source``. We skip the cookie-decode fallback
    that ``get_current_user_from_request`` does (it's only useful when
    middleware failed to populate state) and just read state directly —
    cheaper and works for both prod and the stub test middleware.
    """
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


# ---------------------------------------------------------------------------
# Quota / safety limits
# ---------------------------------------------------------------------------

MAX_ENABLED_JOBS_PER_USER: int = 20
MIN_CRON_INTERVAL_SECONDS: int = 1800  # 30 minutes — blocks runaway loops


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TriggerModel(BaseModel):
    """Free-form trigger descriptor accepted by the create endpoint.

    The API accepts either:

    - ``{"when": "0 9 * * *"}`` — a user-facing string parsed by
      ``parse_user_when`` (cron / every / at)
    - ``{"kind": "cron", "expr": "0 9 * * *", "tz": "UTC"}`` — a
      structured trigger dict (round-trips from GET → PATCH)
    """

    when: str | None = None
    kind: Literal["at", "every", "cron"] | None = None
    # at
    at: str | None = None
    # every
    every_seconds: int | None = None
    anchor_ms: int | None = None
    # cron
    expr: str | None = None
    tz: str | None = None
    stagger_ms: int | None = None


class CreateJobRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    trigger: TriggerModel
    thread_strategy: Literal["new", "fixed"] = "new"
    fixed_thread_id: str | None = None
    agent_name: str | None = None
    delete_after_run: bool | None = None
    source_channel: str = "web"


class PatchJobRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    trigger: TriggerModel | None = None
    thread_strategy: Literal["new", "fixed"] | None = None
    fixed_thread_id: str | None = None
    agent_name: str | None = None
    enabled: bool | None = None
    delete_after_run: bool | None = None


class RunNowRequest(BaseModel):
    mode: Literal["force", "due"] = "force"


class JobResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: str
    trigger_type: str
    trigger_data: dict[str, Any]
    thread_strategy: str
    fixed_thread_id: str | None = None
    agent_name: str | None = None
    enabled: bool
    next_run_at: str
    last_run_at: str | None = None
    last_status: str | None = None
    consecutive_errors: int
    next_retry_at: str | None = None
    delete_after_run: bool
    source_channel: str
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    count: int


class JobRunResponse(BaseModel):
    id: str
    job_id: str
    thread_id: str
    status: str
    error_msg: str | None = None
    token_usage: int
    duration_ms: int
    started_at: str
    finished_at: str | None = None


class JobRunListResponse(BaseModel):
    runs: list[JobRunResponse]
    count: int


class QuotaResponse(BaseModel):
    enabled_jobs: int
    max_enabled_jobs: int
    remaining: int


class CreateJobResponse(BaseModel):
    job: JobResponse


class RunNowResponse(BaseModel):
    run_id: str | None
    status: str
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_repos() -> tuple[ScheduledJobRepository, ScheduledJobRunRepository]:
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="persistence engine not initialised")
    return ScheduledJobRepository(sf), ScheduledJobRunRepository(sf)


def _trigger_model_to_trigger(model: TriggerModel):
    """Resolve a TriggerModel from the API into a Trigger instance."""
    try:
        if model.when is not None:
            return parse_user_when(model.when, tz=model.tz or "UTC")

        if model.kind == "at":
            if not model.at:
                raise HTTPException(status_code=422, detail="trigger.kind='at' requires trigger.at")
            return AtTrigger(at=model.at)
        if model.kind == "every":
            if not model.every_seconds:
                raise HTTPException(status_code=422, detail="trigger.kind='every' requires trigger.every_seconds")
            return EveryTrigger(seconds=model.every_seconds, anchor_ms=model.anchor_ms)
        if model.kind == "cron":
            if not model.expr:
                raise HTTPException(status_code=422, detail="trigger.kind='cron' requires trigger.expr")
            return CronTrigger(expr=model.expr, tz=model.tz or "UTC", stagger_ms=model.stagger_ms)
    except ValueError as exc:
        # Trigger constructors validate ranges (cron syntax, every minimum).
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    raise HTTPException(status_code=422, detail="trigger must have either 'when' or 'kind'")


def _enforce_cron_min_interval(trigger) -> None:
    """Reject cron expressions whose tightest interval is below the floor."""
    if not isinstance(trigger, CronTrigger):
        return
    # Sample the next two runs and measure the gap.
    now = datetime.now(UTC)
    n1 = trigger.compute_next(None, now=now, job_id="quota-check")
    if n1 is None:
        return
    n2 = trigger.compute_next(n1, now=n1, job_id="quota-check")
    if n2 is None:
        return
    gap = (n2 - n1).total_seconds()
    if gap < MIN_CRON_INTERVAL_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=(f"cron cadence too tight: {int(gap)}s between runs; minimum is {MIN_CRON_INTERVAL_SECONDS}s"),
        )


def _row_to_response(row: dict[str, Any]) -> JobResponse:
    return JobResponse(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        description=row["description"],
        trigger_type=row["trigger_type"],
        trigger_data=row["trigger_data"],
        thread_strategy=row["thread_strategy"],
        fixed_thread_id=row.get("fixed_thread_id"),
        agent_name=row.get("agent_name"),
        enabled=row["enabled"],
        next_run_at=row["next_run_at"],
        last_run_at=row.get("last_run_at"),
        last_status=row.get("last_status"),
        consecutive_errors=row.get("consecutive_errors", 0),
        next_retry_at=row.get("next_retry_at"),
        delete_after_run=row["delete_after_run"],
        source_channel=row["source_channel"],
        created_at=row["created_at"],
        updated_at=row.get("updated_at", row["created_at"]),
    )


def _run_row_to_response(row: dict[str, Any]) -> JobRunResponse:
    return JobRunResponse(
        id=row["id"],
        job_id=row["job_id"],
        thread_id=row["thread_id"],
        status=row["status"],
        error_msg=row.get("error_msg"),
        token_usage=row.get("token_usage", 0),
        duration_ms=row.get("duration_ms", 0),
        started_at=row["started_at"],
        finished_at=row.get("finished_at"),
    )


class _RequestUserShim:
    """Adapter so ``set_current_user`` accepts the auth ``User`` object.

    ``CurrentUser`` is a structural Protocol requiring only ``.id: str``;
    the auth ``User`` model already satisfies it. This shim exists only
    to make the intent explicit at the call site.
    """

    def __init__(self, user: Any) -> None:
        self.id: str = str(user.id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=JobListResponse)
async def list_jobs(
    request: Request,
    include_disabled: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List the caller's scheduled jobs."""
    user = await _require_user(request)
    jobs_repo, _ = _get_repos()

    token = set_current_user(_RequestUserShim(user))
    try:
        rows = await jobs_repo.list_jobs(
            include_disabled=include_disabled,
            limit=limit,
            offset=offset,
        )
    finally:
        reset_current_user(token)

    return JobListResponse(jobs=[_row_to_response(r) for r in rows], count=len(rows))


@router.post("", response_model=CreateJobResponse, status_code=201)
async def create_job(request: Request, body: CreateJobRequest):
    """Create a new scheduled job for the caller.

    Enforces:

    - Per-user enabled-job cap (``MAX_ENABLED_JOBS_PER_USER``)
    - Minimum cron cadence (``MIN_CRON_INTERVAL_SECONDS``)
    - One-shot ``at`` defaults to ``delete_after_run=True``; recurring
      triggers default to ``False``. Caller may override.
    """
    user = await _require_user(request)
    jobs_repo, _ = _get_repos()

    trigger = _trigger_model_to_trigger(body.trigger)
    _enforce_cron_min_interval(trigger)

    # Resolve delete_after_run default
    if body.delete_after_run is None:
        delete_after_run = isinstance(trigger, AtTrigger)
    else:
        delete_after_run = body.delete_after_run

    now = datetime.now(UTC)
    job_id = jobs_repo.new_job_id()
    next_run_at = trigger.compute_next(None, now=now, job_id=job_id)
    if next_run_at is None:
        raise HTTPException(status_code=422, detail="trigger has no upcoming run time")

    token = set_current_user(_RequestUserShim(user))
    try:
        current_count = await jobs_repo.count_enabled_jobs()
        if current_count >= MAX_ENABLED_JOBS_PER_USER:
            raise HTTPException(
                status_code=429,
                detail=(f"enabled-job quota exhausted: {current_count}/{MAX_ENABLED_JOBS_PER_USER}"),
            )

        row = await jobs_repo.create_job(
            name=body.name,
            description=body.description,
            trigger_type=trigger.type,
            trigger_data=trigger.to_dict(),
            next_run_at=next_run_at,
            thread_strategy=body.thread_strategy,
            fixed_thread_id=body.fixed_thread_id,
            agent_name=body.agent_name,
            delete_after_run=delete_after_run,
            source_channel=body.source_channel,
            job_id=job_id,
        )
    finally:
        reset_current_user(token)

    return CreateJobResponse(job=_row_to_response(row))


@router.get("/quota", response_model=QuotaResponse)
async def get_quota(request: Request):
    """Return the caller's quota usage."""
    user = await _require_user(request)
    jobs_repo, _ = _get_repos()

    token = set_current_user(_RequestUserShim(user))
    try:
        used = await jobs_repo.count_enabled_jobs()
    finally:
        reset_current_user(token)

    return QuotaResponse(
        enabled_jobs=used,
        max_enabled_jobs=MAX_ENABLED_JOBS_PER_USER,
        remaining=max(0, MAX_ENABLED_JOBS_PER_USER - used),
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(request: Request, job_id: str):
    user = await _require_user(request)
    jobs_repo, _ = _get_repos()

    token = set_current_user(_RequestUserShim(user))
    try:
        row = await jobs_repo.get_job(job_id)
    finally:
        reset_current_user(token)

    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _row_to_response(row)


@router.patch("/{job_id}", response_model=JobResponse)
async def patch_job(request: Request, job_id: str, body: PatchJobRequest):
    user = await _require_user(request)
    jobs_repo, _ = _get_repos()

    token = set_current_user(_RequestUserShim(user))
    try:
        existing = await jobs_repo.get_job(job_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="job not found")

        trigger_type = None
        trigger_data = None
        next_run_at = None
        if body.trigger is not None:
            new_trigger = _trigger_model_to_trigger(body.trigger)
            _enforce_cron_min_interval(new_trigger)
            trigger_type = new_trigger.type
            trigger_data = new_trigger.to_dict()
            next_run_at = new_trigger.compute_next(None, now=datetime.now(UTC), job_id=job_id)
            if next_run_at is None:
                raise HTTPException(status_code=422, detail="trigger has no upcoming run time")

        updated = await jobs_repo.update_job_spec(
            job_id,
            name=body.name,
            description=body.description,
            trigger_type=trigger_type,
            trigger_data=trigger_data,
            next_run_at=next_run_at,
            thread_strategy=body.thread_strategy,
            fixed_thread_id=body.fixed_thread_id,
            agent_name=body.agent_name,
            enabled=body.enabled,
            delete_after_run=body.delete_after_run,
        )
    finally:
        reset_current_user(token)

    if updated is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _row_to_response(updated)


@router.delete("/{job_id}", status_code=204)
async def delete_job(request: Request, job_id: str):
    user = await _require_user(request)
    jobs_repo, _ = _get_repos()

    token = set_current_user(_RequestUserShim(user))
    try:
        ok = await jobs_repo.delete_job(job_id)
    finally:
        reset_current_user(token)

    if not ok:
        raise HTTPException(status_code=404, detail="job not found")


@router.post("/{job_id}/run", response_model=RunNowResponse)
async def run_job_now(request: Request, job_id: str, body: RunNowRequest):
    """Trigger an immediate manual run.

    Implementation note: PR #4 only persists the intent — it does not
    actually invoke the executor. The Scheduler tick loop will pick the
    job up within 1 second if ``mode=force`` (we set ``next_run_at=now``
    in that case). For ``mode=due`` we leave the schedule alone.
    """
    user = await _require_user(request)
    jobs_repo, _ = _get_repos()

    token = set_current_user(_RequestUserShim(user))
    try:
        existing = await jobs_repo.get_job(job_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="job not found")

        if body.mode == "force":
            await jobs_repo.update_scheduling_state(
                job_id,
                next_run_at=datetime.now(UTC),
            )
            return RunNowResponse(run_id=None, status="queued", message="job scheduled for immediate execution")
        # mode == "due"
        next_run_at = coerce_datetime(existing.get("next_run_at"))
        if next_run_at is not None and next_run_at <= datetime.now(UTC):
            return RunNowResponse(run_id=None, status="queued", message="job already due")
        return RunNowResponse(run_id=None, status="skipped", message="job not due yet")
    finally:
        reset_current_user(token)


@router.get("/{job_id}/runs", response_model=JobRunListResponse)
async def list_job_runs(
    request: Request,
    job_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    user = await _require_user(request)
    _, runs_repo = _get_repos()

    token = set_current_user(_RequestUserShim(user))
    try:
        rows = await runs_repo.list_runs_for_job(job_id, limit=limit, offset=offset)
    finally:
        reset_current_user(token)

    return JobRunListResponse(
        runs=[_run_row_to_response(r) for r in rows],
        count=len(rows),
    )
