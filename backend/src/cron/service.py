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
import os
import tempfile
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

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


@dataclass
class _JobExecutionResult:
    """Captured outcome for a single cron job execution."""

    job_id: str
    last_run_at_ms: int
    next_run_at_ms: int | None
    last_status: Literal["ok", "error"]
    last_error: str | None


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
        await cron.add_job(
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
        self._store_lock = asyncio.Lock()
        self._executing_job_ids: set[str] = set()

    def _get_store_mtime(self) -> float | None:
        """Read the current store file modification time, if it exists."""
        try:
            if not self.store_path.exists():
                return None
            return self.store_path.stat().st_mtime
        except OSError:
            return None

    def _read_store_from_disk(self) -> tuple[CronStore, float | None]:
        """Read and deserialize the persisted cron store."""
        with open(self.store_path, encoding="utf-8") as f:
            data = json.load(f)

        jobs = [CronJob.from_dict(job) for job in data.get("jobs", [])]
        store = CronStore(version=data.get("version", 1), jobs=jobs)
        return store, self._get_store_mtime()

    def _write_store_to_disk(self, store: CronStore) -> float | None:
        """Atomically persist the cron store to disk."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": store.version,
            "jobs": [job.to_dict() for job in store.jobs],
        }

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.store_path.stem}-",
            suffix=".tmp",
            dir=self.store_path.parent,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(self.store_path)
            return self._get_store_mtime()
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    async def _load_store_locked(self) -> CronStore:
        """Load store from disk, with hot-reload detection."""
        current_mtime = await asyncio.to_thread(self._get_store_mtime)
        if self._store is not None and current_mtime != self._last_mtime:
            logger.info("Cron: jobs.json modified externally, reloading")
            self._store = None

        if self._store is None:
            if current_mtime is None:
                self._store = CronStore()
                self._last_mtime = None
            else:
                try:
                    self._store, self._last_mtime = await asyncio.to_thread(self._read_store_from_disk)
                except Exception as e:
                    logger.error(f"Failed to load cron store: {e}")
                    self._store = CronStore()
                    self._last_mtime = current_mtime

        return self._store

    async def _save_store_locked(self) -> None:
        """Save store to disk."""
        if self._store is None:
            return

        try:
            self._last_mtime = await asyncio.to_thread(self._write_store_to_disk, self._store)
        except Exception as e:
            logger.error(f"Failed to save cron store: {e}")

    def _recompute_next_runs_locked(self, store: CronStore, *, preserve_existing: bool = False) -> None:
        """Recompute next run times for jobs that need them."""
        now = _now_ms()
        for job in store.jobs:
            if job.enabled:
                if preserve_existing and job.state.next_run_at_ms is not None:
                    continue
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)
            else:
                job.state.next_run_at_ms = None

    def _get_next_wake_ms_locked(self, store: CronStore | None = None) -> int | None:
        """Get the earliest next run time among enabled jobs."""
        active_store = store if store is not None else self._store
        if active_store is None:
            return None

        times = [
            job.state.next_run_at_ms
            for job in active_store.jobs
            if job.id not in self._executing_job_ids and job.enabled and job.state.next_run_at_ms
        ]
        return min(times) if times else None

    def _copy_job(self, job: CronJob) -> CronJob:
        """Create an isolated snapshot so job execution can happen outside the store lock."""
        return CronJob.from_dict(job.to_dict())

    def _apply_execution_result_locked(self, store: CronStore, result: _JobExecutionResult) -> bool:
        """Apply a completed run back onto the persisted job, if it still exists."""
        current_job = next((job for job in store.jobs if job.id == result.job_id), None)
        if current_job is None:
            logger.info("Cron: job %s was removed while running; skipping state update", result.job_id)
            return False

        current_job.state.last_run_at_ms = result.last_run_at_ms
        current_job.state.last_status = result.last_status
        current_job.state.last_error = result.last_error

        if current_job.schedule.kind == "at":
            if current_job.delete_after_run and result.last_status == "ok":
                store.jobs.remove(current_job)
                logger.info(f"Cron: deleted one-time job '{current_job.name}'")
            else:
                current_job.enabled = False
                current_job.state.next_run_at_ms = None
                logger.info(f"Cron: disabled one-time job '{current_job.name}'")
        else:
            current_job.state.next_run_at_ms = result.next_run_at_ms if current_job.enabled else None

        return True

    async def start(self) -> None:
        """Start the cron service."""
        async with self._store_lock:
            if self._running:
                logger.warning("CronService already running")
                return

            store = await self._load_store_locked()
            self._recompute_next_runs_locked(store, preserve_existing=True)
            await self._save_store_locked()
            self._running = True
            job_count = len(store.jobs)

        self._arm_timer()
        logger.info(f"CronService started with {job_count} jobs")

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

        next_wake = self._get_next_wake_ms_locked()
        if not next_wake or not self._running:
            return

        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        async def tick():
            try:
                await asyncio.sleep(delay_s)
            except asyncio.CancelledError:
                pass
                return

            # The timer task only owns the waiting period. Once it wakes up,
            # release the slot so admin operations can safely re-arm timers
            # without cancelling an in-flight cron execution.
            self._timer_task = None

            if not self._running:
                return

            try:
                await self._on_timer()
            except Exception as e:
                logger.error(f"Cron timer error: {e}")

        self._timer_task = asyncio.create_task(tick())
        logger.debug(f"Cron: next wake in {delay_s:.1f}s")

    async def _on_timer(self) -> None:
        """Handle timer wake-up."""
        async with self._store_lock:
            store = await self._load_store_locked()
            self._recompute_next_runs_locked(store, preserve_existing=True)
            now = _now_ms()
            due_jobs = [
                self._copy_job(job)
                for job in store.jobs
                if (
                    job.id not in self._executing_job_ids
                    and job.enabled
                    and job.state.next_run_at_ms
                    and now >= job.state.next_run_at_ms
                )
            ]
            if not due_jobs:
                await self._save_store_locked()
                self._arm_timer()
                return

            for job in due_jobs:
                self._executing_job_ids.add(job.id)

        try:
            execution_results = [await self._execute_job(job) for job in due_jobs]

            async with self._store_lock:
                store = await self._load_store_locked()
                for result in execution_results:
                    self._apply_execution_result_locked(store, result)
                await self._save_store_locked()
        finally:
            async with self._store_lock:
                for job in due_jobs:
                    self._executing_job_ids.discard(job.id)

        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> _JobExecutionResult:
        """Execute a single job snapshot outside the store lock."""
        start_ms = _now_ms()
        scheduled_run_at_ms = job.state.next_run_at_ms
        logger.info(f"Cron: executing job '{job.name}' ({job.id})")

        try:
            if self.on_job:
                await self.on_job(job)
            job.state.last_status = "ok"
            job.state.last_error = None
        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error(f"Cron job '{job.name}' failed: {e}")

        job.state.last_run_at_ms = start_ms

        # Handle one-time tasks
        if job.schedule.kind == "at":
            job.enabled = False
            job.state.next_run_at_ms = None
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

        return _JobExecutionResult(
            job_id=job.id,
            last_run_at_ms=job.state.last_run_at_ms,
            next_run_at_ms=job.state.next_run_at_ms,
            last_status=job.state.last_status,
            last_error=job.state.last_error,
        )

    # --- Public API ---

    async def get_jobs(self) -> list[CronJob]:
        """Get all jobs."""
        async with self._store_lock:
            store = await self._load_store_locked()
            return list(store.jobs)

    async def list_jobs(self, include_disabled: bool = False) -> list[dict]:
        """List all jobs as dictionaries."""
        async with self._store_lock:
            store = await self._load_store_locked()
            jobs = list(store.jobs)

        if not include_disabled:
            jobs = [j for j in jobs if j.enabled]
        jobs = sorted(jobs, key=lambda job: job.state.next_run_at_ms or float("inf"))
        return [j.to_dict() for j in jobs]

    async def add_job(
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

        async with self._store_lock:
            now_ms = _now_ms()
            next_run_at_ms = _compute_next_run(schedule, now_ms) if enabled else None
            if enabled and next_run_at_ms is None:
                raise ValueError("schedule does not produce a future run time")

            job = CronJob(
                id=_generate_id(),
                name=name,
                enabled=enabled,
                schedule=schedule,
                payload=payload if isinstance(payload, CronPayload) else CronPayload(**payload),  # type: ignore
                delete_after_run=delete_after_run,
                created_at_ms=now_ms,
            )
            job.state.next_run_at_ms = next_run_at_ms

            store = await self._load_store_locked()
            store.jobs.append(job)
            await self._save_store_locked()

        self._arm_timer()

        logger.info(f"Cron: added job '{name}' ({job.id}), next run at {job.state.next_run_at_ms}")
        return job

    async def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        removed = False
        async with self._store_lock:
            store = await self._load_store_locked()
            for i, job in enumerate(store.jobs):
                if job.id == job_id:
                    del store.jobs[i]
                    await self._save_store_locked()
                    removed = True
                    break

        if removed:
            self._arm_timer()
            logger.info(f"Cron: removed job {job_id}")
        return removed

    async def enable_job(self, job_id: str, enabled: bool = True) -> bool:
        """Enable or disable a job."""
        updated = False
        async with self._store_lock:
            store = await self._load_store_locked()
            for job in store.jobs:
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
                    await self._save_store_locked()
                    updated = True
                    break

        if updated:
            self._arm_timer()
            logger.info(f"Cron: {'enabled' if enabled else 'disabled'} job {job_id}")
        return updated

    async def run_job(self, job_id: str, force: bool = True) -> str | None:
        """Manually trigger a job.

        Args:
            job_id: Job ID to run
            force: Run even if disabled

        Returns:
            Job result or None if not found
        """
        job_to_run: CronJob | None = None
        while job_to_run is None:
            should_wait = False
            async with self._store_lock:
                store = await self._load_store_locked()
                for job in store.jobs:
                    if job.id != job_id or not (job.enabled or force):
                        continue
                    if job.id in self._executing_job_ids:
                        should_wait = True
                    else:
                        self._executing_job_ids.add(job.id)
                        job_to_run = self._copy_job(job)
                    break

            if job_to_run is not None:
                break
            if not should_wait:
                return None

            await asyncio.sleep(0.01)

        try:
            execution_result = await self._execute_job(job_to_run)

            async with self._store_lock:
                store = await self._load_store_locked()
                self._apply_execution_result_locked(store, execution_result)
                await self._save_store_locked()
        finally:
            async with self._store_lock:
                self._executing_job_ids.discard(job_id)

        self._arm_timer()
        return execution_result.last_error if execution_result.last_status == "error" else "ok"

    async def status(self) -> dict:
        """Get service status."""
        async with self._store_lock:
            store = await self._load_store_locked()
            jobs = list(store.jobs)

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
        from deerflow.config.paths import get_paths

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
