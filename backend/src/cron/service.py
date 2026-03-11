"""CronService - Core scheduling service for deer-flow.

This module provides a precise timer-based cron service that:
- Uses asyncio.sleep() to wait exactly until the next task time (no polling)
- Persists jobs to a JSON file
- Supports one-time, interval, and cron expression scheduling
- Integrates with deer-flow's LangGraph agent system
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from .types import CronJob, CronPayload, CronSchedule, _generate_id, _now_ms

logger = logging.getLogger(__name__)


class NoFutureRunTimeError(ValueError):
    """Raised when a job cannot be enabled because it has no future run time."""


def _compute_next_run(
    schedule: CronSchedule,
    now_ms: int,
    *,
    anchor_ms: int | None = None,
) -> int | None:
    """Compute next run time in milliseconds.

    Args:
        schedule: The schedule configuration
        now_ms: Current time in milliseconds
        anchor_ms: Optional cadence anchor for interval schedules

    Returns:
        Next run time in milliseconds, or None if no more runs
    """
    if schedule.kind == "at":
        # One-time task: only valid if in the future
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        # Interval task: preserve cadence when anchored to the previous schedule.
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        if anchor_ms is not None:
            next_run_at_ms = anchor_ms + schedule.every_ms
            if next_run_at_ms > now_ms:
                return next_run_at_ms
            skipped_intervals = ((now_ms - next_run_at_ms) // schedule.every_ms) + 1
            return next_run_at_ms + skipped_intervals * schedule.every_ms
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        # Cron expression: use croniter to compute next run
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter

            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            cron = croniter(schedule.expr, base_dt)
            next_dt = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception as e:
            logger.error(f"Failed to compute next run for cron expression: {e}")
            return None

    return None


def _validate_schedule_for_add(schedule: CronSchedule) -> None:
    """Validate a schedule before it is persisted."""
    if schedule.tz and schedule.kind != "cron":
        raise ValueError("timezone can only be used with cron schedules")

    if schedule.kind == "at":
        if schedule.at_ms is None:
            raise ValueError("at schedules require 'at_ms'")
        return

    if schedule.kind == "every":
        if schedule.every_ms is None or schedule.every_ms <= 0:
            raise ValueError("every schedules require a positive 'every_ms'")
        return

    if schedule.kind == "cron":
        if not schedule.expr:
            raise ValueError("cron schedules require 'expr'")
        if schedule.tz:
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(schedule.tz)
            except Exception as exc:
                raise ValueError(f"unknown timezone '{schedule.tz}'") from exc

        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter

            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            croniter(schedule.expr, datetime.fromtimestamp(_now_ms() / 1000, tz=tz))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"invalid cron expression '{schedule.expr}'") from exc
        return

    raise ValueError(f"unsupported schedule kind '{schedule.kind}'")


@dataclass
class CronStore:
    """Storage container for cron jobs."""

    version: int = 1
    jobs: list[CronJob] = None  # type: ignore

    def __post_init__(self):
        if self.jobs is None:
            self.jobs = []


class CronService:
    """Periodic task scheduling service.

    Core mechanism:
    1. Find the nearest task time
    2. asyncio.sleep() until that time (zero CPU overhead)
    3. Execute due tasks
    4. Recompute next times and repeat

    Example:
        cron = CronService(store_path=Path("jobs.json"))
        cron.on_job = my_callback  # Called when job triggers

        # Add a one-time task
        cron.add_job(
            name="Reminder",
            schedule=CronSchedule(kind="at", at_ms=future_timestamp_ms),
            payload=CronPayload(message="Time to check emails!"),
        )

        # Start the service
        await cron.start()
    """

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
    ):
        self.store_path = Path(store_path)
        self.on_job = on_job
        self._store: CronStore | None = None
        self._running = False
        self._timer_task: asyncio.Task | None = None
        self._last_mtime: float | None = None

    @property
    def jobs(self) -> list[CronJob]:
        """Get all jobs."""
        if self._store is None:
            self._load_store()
        return self._store.jobs if self._store else []

    def _load_store(self) -> CronStore:
        """Load store from disk, with hot-reload detection."""
        if self._store and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            if mtime != self._last_mtime:
                logger.info("Cron: jobs.json modified externally, reloading")
                self._store = None

        if self._store is None:
            if self.store_path.exists():
                try:
                    with open(self.store_path, encoding="utf-8") as f:
                        data = json.load(f)
                    jobs = [CronJob.from_dict(j) for j in data.get("jobs", [])]
                    self._store = CronStore(version=data.get("version", 1), jobs=jobs)
                    self._last_mtime = self.store_path.stat().st_mtime
                except Exception as e:
                    logger.error(f"Failed to load cron store: {e}")
                    self._store = CronStore()
            else:
                self._store = CronStore()

        return self._store

    def _save_store(self) -> None:
        """Save store to disk."""
        if self._store is None:
            return

        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": self._store.version,
                "jobs": [job.to_dict() for job in self._store.jobs],
            }
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._last_mtime = self.store_path.stat().st_mtime
        except Exception as e:
            logger.error(f"Failed to save cron store: {e}")

    def _recompute_next_runs(self, *, preserve_existing: bool = False) -> None:
        """Recompute next run times for jobs that need them."""
        now = _now_ms()
        for job in self.jobs:
            if job.enabled:
                if preserve_existing and job.state.next_run_at_ms is not None:
                    continue
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)
            else:
                job.state.next_run_at_ms = None

    def _get_next_wake_ms(self) -> int | None:
        """Get the earliest next run time among enabled jobs."""
        times = [j.state.next_run_at_ms for j in self.jobs if j.enabled and j.state.next_run_at_ms]
        return min(times) if times else None

    async def start(self) -> None:
        """Start the cron service."""
        if self._running:
            logger.warning("CronService already running")
            return

        self._load_store()
        self._recompute_next_runs(preserve_existing=True)
        self._save_store()
        self._running = True
        self._arm_timer()
        logger.info(f"CronService started with {len(self.jobs)} jobs")

    def stop(self) -> None:
        """Stop the cron service."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        logger.info("CronService stopped")

    def _arm_timer(self) -> None:
        """Set the timer for the next wake-up."""
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return

        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        async def tick():
            try:
                await asyncio.sleep(delay_s)
                if self._running:
                    await self._on_timer()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Cron timer error: {e}")

        self._timer_task = asyncio.create_task(tick())
        logger.debug(f"Cron: next wake in {delay_s:.1f}s")

    async def _on_timer(self) -> None:
        """Handle timer wake-up."""
        self._load_store()  # Hot reload
        self._recompute_next_runs(preserve_existing=True)
        now = _now_ms()

        due_jobs = [j for j in self.jobs if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms]

        for job in due_jobs:
            await self._execute_job(job)

        self._save_store()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job."""
        start_ms = _now_ms()
        scheduled_run_at_ms = job.state.next_run_at_ms
        logger.info(f"Cron: executing job '{job.name}' ({job.id})")

        try:
            result = None
            if self.on_job:
                result = await self.on_job(job)
            job.state.last_status = "ok"
            job.state.last_error = None
        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error(f"Cron job '{job.name}' failed: {e}")

        job.state.last_run_at_ms = start_ms

        # Handle one-time tasks
        if job.schedule.kind == "at":
            if job.delete_after_run and job.state.last_status == "ok":
                self._store.jobs.remove(job)  # type: ignore
                logger.info(f"Cron: deleted one-time job '{job.name}'")
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
                logger.info(f"Cron: disabled one-time job '{job.name}'")
        else:
            # Recurring tasks: compute next run
            cadence_anchor_ms = (
                scheduled_run_at_ms
                if scheduled_run_at_ms is not None and scheduled_run_at_ms <= start_ms
                else start_ms
            )
            job.state.next_run_at_ms = _compute_next_run(
                job.schedule,
                _now_ms(),
                anchor_ms=cadence_anchor_ms,
            )

    # --- Public API ---

    def list_jobs(self, include_disabled: bool = False) -> list[dict]:
        """List all jobs as dictionaries."""
        jobs = self.jobs
        if not include_disabled:
            jobs = [j for j in jobs if j.enabled]
        jobs = sorted(jobs, key=lambda job: job.state.next_run_at_ms or float("inf"))
        return [j.to_dict() for j in jobs]

    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        payload: CronPayload,
        enabled: bool = True,
        delete_after_run: bool = False,
    ) -> CronJob:
        """Add a new cron job.

        Args:
            name: Human-readable job name
            schedule: When to run the job
            payload: What to run
            enabled: Whether job is active
            delete_after_run: Auto-delete after one-time execution

        Returns:
            The created CronJob
        """
        _validate_schedule_for_add(schedule)

        next_run_at_ms = _compute_next_run(schedule, _now_ms()) if enabled else None
        if enabled and next_run_at_ms is None:
            raise ValueError("schedule does not produce a future run time")

        job = CronJob(
            id=_generate_id(),
            name=name,
            enabled=enabled,
            schedule=schedule,
            payload=payload if isinstance(payload, CronPayload) else CronPayload(**payload),  # type: ignore
            delete_after_run=delete_after_run,
            created_at_ms=_now_ms(),
        )
        job.state.next_run_at_ms = next_run_at_ms

        self._load_store()
        self._store.jobs.append(job)  # type: ignore
        self._save_store()
        self._arm_timer()

        logger.info(f"Cron: added job '{name}' ({job.id}), next run at {job.state.next_run_at_ms}")
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        self._load_store()
        for i, job in enumerate(self._store.jobs):  # type: ignore
            if job.id == job_id:
                del self._store.jobs[i]  # type: ignore
                self._save_store()
                self._arm_timer()
                logger.info(f"Cron: removed job {job_id}")
                return True
        return False

    def enable_job(self, job_id: str, enabled: bool = True) -> bool:
        """Enable or disable a job."""
        self._load_store()
        for job in self._store.jobs:  # type: ignore
            if job.id == job_id:
                if enabled:
                    next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                    if next_run_at_ms is None:
                        raise NoFutureRunTimeError(
                            f"Job {job_id} cannot be enabled because its schedule has no future run time"
                        )
                    job.enabled = True
                    job.state.next_run_at_ms = next_run_at_ms
                else:
                    job.enabled = False
                    job.state.next_run_at_ms = None
                self._save_store()
                self._arm_timer()
                logger.info(f"Cron: {'enabled' if enabled else 'disabled'} job {job_id}")
                return True
        return False

    async def run_job(self, job_id: str, force: bool = True) -> str | None:
        """Manually trigger a job.

        Args:
            job_id: Job ID to run
            force: Run even if disabled

        Returns:
            Job result or None if not found
        """
        self._load_store()
        for job in self._store.jobs:  # type: ignore
            if job.id == job_id and (job.enabled or force):
                await self._execute_job(job)
                self._save_store()
                self._arm_timer()
                return job.state.last_error if job.state.last_status == "error" else "ok"
        return None

    def status(self) -> dict:
        """Get service status."""
        jobs = self.jobs
        enabled = sum(1 for j in jobs if j.enabled)
        return {
            "running": self._running,
            "jobs": len(jobs),
            "enabled": enabled,
            "disabled": len(jobs) - enabled,
        }


# --- Singleton access ---

_cron_service: CronService | None = None


def get_cron_service() -> CronService | None:
    """Get the singleton CronService instance (if started)."""
    return _cron_service


async def start_cron_service(
    store_path: Path | None = None,
    on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
) -> CronService:
    """Create and start the global CronService."""
    global _cron_service
    if _cron_service is not None:
        return _cron_service

    if store_path is None:
        from src.config.paths import get_paths

        store_path = get_paths().base_dir / "cron" / "jobs.json"

    _cron_service = CronService(store_path=store_path, on_job=on_job)
    await _cron_service.start()
    return _cron_service


def stop_cron_service() -> None:
    """Stop the global CronService."""
    global _cron_service
    if _cron_service is not None:
        _cron_service.stop()
        _cron_service = None
