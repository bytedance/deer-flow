"""Background cron scheduler service."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from deerflow.runtime.scheduler.schemas import CronJobPayload, CronJobRecord
from deerflow.runtime.scheduler.store import CronJobNotFoundError, get_cron_job, list_cron_jobs, list_due_cron_jobs, mark_cron_job_fired

logger = logging.getLogger(__name__)

RunLauncher = Callable[[str, CronJobPayload], Awaitable[Any]]


class CronSchedulerService:
    """Load due cron jobs from the Store and dispatch them into the run lifecycle."""

    def __init__(
        self,
        store,
        run_launcher: RunLauncher,
        *,
        poll_interval: float = 30.0,
    ) -> None:
        self._store = store
        self._run_launcher = run_launcher
        self._poll_interval = poll_interval
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        """Return the background loop task when started."""
        return self._task

    def start(self) -> asyncio.Task[None]:
        """Start the background scheduler loop."""
        if self._task is not None and not self._task.done():
            return self._task

        self._stop_event.clear()
        self._wake_event.clear()
        self._task = asyncio.create_task(self.run_forever())
        return self._task

    async def stop(self) -> None:
        """Stop the background scheduler loop."""
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    def wake(self) -> None:
        """Wake the loop so it can reload jobs after mutations."""
        self._wake_event.set()

    async def trigger_job(self, job_id: str) -> Any:
        """Trigger a cron job immediately without advancing its stored schedule."""
        job = await get_cron_job(self._store, job_id)
        if job is None:
            raise CronJobNotFoundError(job_id)
        return await self._launch_job(job)

    async def dispatch_due_jobs(self, *, now: float | None = None, limit: int = 100) -> list[Any]:
        """Dispatch all due cron jobs and advance their next fire time."""
        jobs = await list_due_cron_jobs(self._store, now=now, limit=limit)
        results = []

        for job in jobs:
            scheduled_fire_at = job.next_fire_at if job.next_fire_at is not None else (now if now is not None else time.time())

            try:
                record = await self._launch_job(job)
            except Exception:
                logger.exception("Cron scheduler failed to dispatch job %s", job.job_id)
                await mark_cron_job_fired(
                    self._store,
                    job.job_id,
                    fired_at=scheduled_fire_at,
                    run_id=None,
                )
                continue

            run_id = getattr(record, "run_id", None)
            await mark_cron_job_fired(
                self._store,
                job.job_id,
                fired_at=scheduled_fire_at,
                run_id=run_id,
            )
            results.append(record)

        return results

    async def compute_sleep_seconds(self, *, now: float | None = None, scan_limit: int = 1000) -> float:
        """Return how long the loop should sleep before scanning again."""
        current_time = now if now is not None else time.time()
        jobs = await list_cron_jobs(self._store, enabled=True, limit=scan_limit, offset=0)
        next_fire_candidates = [job.next_fire_at for job in jobs if job.next_fire_at is not None]
        if not next_fire_candidates:
            return self._poll_interval

        soonest_fire_at = min(next_fire_candidates)
        if soonest_fire_at <= current_time:
            # Avoid a zero-timeout spin when an overdue job keeps failing to dispatch.
            # A short bounded retry interval still lets the loop drain large due sets
            # without pinning the event loop at 100% CPU.
            return min(self._poll_interval, 1.0)

        return min(self._poll_interval, soonest_fire_at - current_time)

    async def run_forever(self) -> None:
        """Run the scheduler loop until stopped."""
        while not self._stop_event.is_set():
            try:
                await self.dispatch_due_jobs()
            except Exception:
                logger.exception("Cron scheduler dispatch failed")

            sleep_seconds = await self.compute_sleep_seconds()
            self._wake_event.clear()

            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=sleep_seconds)
            except TimeoutError:
                continue

    async def _launch_job(self, job: CronJobRecord) -> Any:
        metadata = dict(job.metadata or {})
        scheduler_metadata = dict(metadata.get("scheduler", {}))
        scheduler_metadata.update(
            {
                "job_id": job.job_id,
                "cron": job.cron,
                "timezone": job.timezone,
            }
        )
        metadata["scheduler"] = scheduler_metadata

        payload = CronJobPayload(
            assistant_id=job.assistant_id,
            input=job.input,
            metadata=metadata,
            config=job.config,
            context=job.context,
            multitask_strategy=job.multitask_strategy,
        )
        return await self._run_launcher(job.thread_id, payload)
