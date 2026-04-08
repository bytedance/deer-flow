"""Store-backed persistence helpers for cron scheduler jobs."""

from __future__ import annotations

import time
import uuid

from deerflow.runtime.scheduler.schemas import CronJobCreate, CronJobRecord, CronJobUpdate, compute_next_fire_at

CRON_JOBS_NS: tuple[str, ...] = ("scheduler", "cron_jobs")


class CronJobNotFoundError(KeyError):
    """Raised when a cron job does not exist in the Store."""


async def get_cron_job(store, job_id: str) -> CronJobRecord | None:
    """Fetch a cron job from the Store."""
    item = await store.aget(CRON_JOBS_NS, job_id)
    return CronJobRecord.model_validate(item.value) if item is not None else None


async def put_cron_job(store, record: CronJobRecord) -> None:
    """Persist a cron job record to the Store."""
    await store.aput(CRON_JOBS_NS, record.job_id, record.model_dump(mode="python"), index=False)


async def create_cron_job(
    store,
    payload: CronJobCreate,
    *,
    job_id: str | None = None,
    now: float | None = None,
) -> CronJobRecord:
    """Create and persist a cron job record."""
    current_time = now if now is not None else time.time()
    record = CronJobRecord(
        job_id=job_id or str(uuid.uuid4()),
        created_at=current_time,
        updated_at=current_time,
        next_fire_at=compute_next_fire_at(payload.cron, payload.timezone, now=current_time) if payload.enabled else None,
        **payload.model_dump(),
    )
    await put_cron_job(store, record)
    return record


async def update_cron_job(
    store,
    job_id: str,
    patch: CronJobUpdate,
    *,
    now: float | None = None,
) -> CronJobRecord:
    """Update a cron job and recompute scheduling fields when needed."""
    existing = await get_cron_job(store, job_id)
    if existing is None:
        raise CronJobNotFoundError(job_id)

    current_time = now if now is not None else time.time()
    updates = patch.model_dump(exclude_unset=True)
    merged = existing.model_dump(mode="python")
    merged.update(updates)
    merged["updated_at"] = current_time

    if merged["enabled"]:
        should_recompute = existing.next_fire_at is None or "cron" in updates or "timezone" in updates or ("enabled" in updates and updates["enabled"])
        if should_recompute:
            merged["next_fire_at"] = compute_next_fire_at(merged["cron"], merged["timezone"], now=current_time)
    else:
        merged["next_fire_at"] = None

    record = CronJobRecord.model_validate(merged)
    await put_cron_job(store, record)
    return record


async def delete_cron_job(store, job_id: str) -> bool:
    """Delete a cron job if it exists."""
    existing = await get_cron_job(store, job_id)
    if existing is None:
        return False
    await store.adelete(CRON_JOBS_NS, job_id)
    return True


async def list_cron_jobs(
    store,
    *,
    thread_id: str | None = None,
    enabled: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CronJobRecord]:
    """List cron jobs with simple exact-match filters."""
    filters = {}
    if thread_id is not None:
        filters["thread_id"] = thread_id
    if enabled is not None:
        filters["enabled"] = enabled

    items = await store.asearch(CRON_JOBS_NS, filter=filters or None, limit=limit, offset=offset)
    return [CronJobRecord.model_validate(item.value) for item in items]


async def list_due_cron_jobs(
    store,
    *,
    now: float | None = None,
    limit: int = 100,
    scan_limit: int = 1000,
) -> list[CronJobRecord]:
    """Return enabled cron jobs whose next fire time is due."""
    current_time = now if now is not None else time.time()
    jobs = await list_cron_jobs(store, enabled=True, limit=scan_limit, offset=0)
    due_jobs = [job for job in jobs if job.next_fire_at is not None and job.next_fire_at <= current_time]
    due_jobs.sort(key=lambda job: (job.next_fire_at, job.created_at, job.job_id))
    return due_jobs[:limit]


async def mark_cron_job_fired(
    store,
    job_id: str,
    *,
    fired_at: float | None = None,
    run_id: str | None = None,
) -> CronJobRecord:
    """Persist the latest dispatch and advance the next fire timestamp."""
    existing = await get_cron_job(store, job_id)
    if existing is None:
        raise CronJobNotFoundError(job_id)

    current_time = fired_at if fired_at is not None else time.time()
    updated = existing.model_copy(
        update={
            "updated_at": current_time,
            "last_fire_at": current_time,
            "last_run_id": run_id,
            "next_fire_at": compute_next_fire_at(existing.cron, existing.timezone, now=current_time) if existing.enabled else None,
        }
    )
    await put_cron_job(store, updated)
    return updated
