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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .timezones import get_schedule_timezone, normalize_cron_schedule_timezone, resolve_timezone
from .types import CronJob, CronPayload, CronSchedule, _generate_id, _now_ms

logger = logging.getLogger(__name__)


class NoFutureRunTimeError(ValueError):
    """Raised when a job cannot be enabled because it has no future run time."""


class CronStoreError(RuntimeError):
    """Base class for cron store read/write failures."""


class CronStoreUnavailableError(CronStoreError):
    """Raised when the cron store cannot be safely read."""


class CronStorePersistenceError(CronStoreError):
    """Raised when the cron store cannot be safely persisted."""


class CronServiceStoppingError(RuntimeError):
    """Raised when a queued or inflight run is aborted during service shutdown."""


class CronServiceShutdownTimeoutError(TimeoutError):
    """Raised when graceful shutdown cannot finish within the requested timeout."""


_quarantined_store_paths: dict[str, str] = {}


def _store_quarantine_key(store_path: Path) -> str:
    """Return a normalized key for per-process store quarantine tracking."""
    return os.path.normcase(str(store_path.resolve()))


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
            from croniter import croniter

            base_time = now_ms / 1000
            tz = get_schedule_timezone(schedule)
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
                resolve_timezone(schedule.tz)
            except Exception as exc:
                raise ValueError(f"unknown timezone '{schedule.tz}'") from exc

        try:
            from croniter import croniter

            tz = get_schedule_timezone(schedule)
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
    jobs: list[CronJob] = field(default_factory=list)


@dataclass
class _JobExecutionResult:
    """Captured outcome for a single cron job execution."""

    job_id: str
    last_run_at_ms: int
    next_run_at_ms: int | None
    last_status: Literal["ok", "error"]
    last_error: str | None


@dataclass
class _ManualRunResult:
    """Outcome for a manual run request."""

    status: Literal["executed", "ignored"]
    result: str


@dataclass
class _QueuedRun:
    """A reserved cron run waiting for background execution."""

    job: CronJob
    source: Literal["timer", "manual"]
    generation: int
    completion_future: asyncio.Future[_ManualRunResult] | None = None


@dataclass
class _CompletedRun:
    """A finished cron run waiting for single-writer state application."""

    queued_run: _QueuedRun
    result: _JobExecutionResult


def _manual_result_from_execution(result: _JobExecutionResult) -> _ManualRunResult:
    """Translate an execution result into the public manual-run response model."""
    return _ManualRunResult(
        status="executed",
        result=result.last_error if result.last_status == "error" else "ok",
    )


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
        *,
        max_concurrent_runs: int = 4,
    ):
        self._store_retry_delay_s = 5.0
        self.store_path = Path(store_path)
        self._store_quarantine_key = _store_quarantine_key(self.store_path)
        self.on_job = on_job
        self._max_concurrent_runs = max(1, max_concurrent_runs)
        self._store: CronStore | None = None
        self._running = False
        self._timer_task: asyncio.Task | None = None
        self._last_mtime: int | None = None
        self._store_lock = asyncio.Lock()
        self._executing_job_ids: set[str] = set()
        self._running_job_ids: set[str] = set()
        self._store_error: str | None = None
        self._store_error_action: Literal["stat", "load", "save"] | None = None
        self._store_error_mtime: int | None = None
        self._store_sync_pending = False
        self._run_queue: asyncio.Queue[_QueuedRun] | None = None
        self._result_queue: asyncio.Queue[_CompletedRun] | None = None
        self._worker_tasks: list[asyncio.Task] = []
        self._result_writer_task: asyncio.Task | None = None
        self._accepting_new_runs = False
        self._shutting_down = False
        self._hard_stop_requested = False
        self._background_generation = 0
        self._reserved_runs: dict[str, _QueuedRun] = {}
        self._applying_job_ids: set[str] = set()

    def _ensure_background_processors_locked(self) -> None:
        """Start background workers and the single-writer loop when needed."""
        if self._shutting_down:
            raise CronServiceStoppingError("CronService is shutting down")
        if self._run_queue is None:
            self._run_queue = asyncio.Queue()
        if self._result_queue is None:
            self._result_queue = asyncio.Queue()

        self._prune_background_processors()
        starting_index = len(self._worker_tasks)
        missing_workers = self._max_concurrent_runs - len(self._worker_tasks)
        for worker_index in range(missing_workers):
            task_name = f"cron-worker-{starting_index + worker_index + 1}"
            self._worker_tasks.append(asyncio.create_task(self._worker_loop(), name=task_name))

        if self._result_writer_task is None or self._result_writer_task.done():
            self._result_writer_task = asyncio.create_task(
                self._result_writer_loop(),
                name="cron-result-writer",
            )

        self._accepting_new_runs = True

    def _request_cancel_background_processors(self) -> list[asyncio.Task]:
        """Cancel worker/writer tasks and detach them from the service state."""
        tasks: list[asyncio.Task] = []
        if self._result_writer_task is not None:
            self._result_writer_task.cancel()
            tasks.append(self._result_writer_task)
            self._result_writer_task = None

        for task in self._worker_tasks:
            task.cancel()
            tasks.append(task)
        self._worker_tasks = []

        return tasks

    def _prune_background_processors(self) -> None:
        """Drop completed worker/writer tasks from the service state."""
        self._worker_tasks = [task for task in self._worker_tasks if not task.done()]
        if self._result_writer_task is not None and self._result_writer_task.done():
            self._result_writer_task = None

    async def _wait_background_processors(
        self,
        tasks: list[asyncio.Task],
        *,
        timeout_s: float | None,
    ) -> set[asyncio.Task]:
        """Wait for background processors that belong to the current event loop."""
        if not tasks:
            return set()

        current_loop = asyncio.get_running_loop()
        waitable_tasks = [task for task in tasks if not task.done() and task.get_loop() is current_loop]
        if not waitable_tasks:
            return set()

        if timeout_s is None:
            await asyncio.gather(*waitable_tasks, return_exceptions=True)
            return set()

        _, pending = await asyncio.wait(waitable_tasks, timeout=timeout_s)
        return pending

    async def _cancel_background_processors(self, *, timeout_s: float | None = None) -> set[asyncio.Task]:
        """Cancel worker/writer tasks and optionally bound how long we wait for exit."""
        tasks = self._request_cancel_background_processors()
        return await self._wait_background_processors(tasks, timeout_s=timeout_s)

    def _drain_queue_nowait(self, queue: asyncio.Queue[Any] | None) -> list[Any]:
        """Remove and return all currently queued items, marking them done."""
        drained_items: list[Any] = []
        if queue is None:
            return drained_items

        while True:
            try:
                drained_items.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                return drained_items
            else:
                queue.task_done()

    def _reserve_run_locked(self, queued_run: _QueuedRun) -> None:
        """Register an in-flight run so shutdown can account for it."""
        self._executing_job_ids.add(queued_run.job.id)
        self._reserved_runs[queued_run.job.id] = queued_run

    def _raise_if_store_quarantined(self) -> None:
        """Block restarts for stores quarantined after a hard stop during commit."""
        reason = _quarantined_store_paths.get(self._store_quarantine_key)
        if reason is not None:
            raise RuntimeError(reason)

    def _quarantine_store(self, reason: str) -> None:
        """Prevent the current store path from being restarted in this process."""
        _quarantined_store_paths[self._store_quarantine_key] = reason

    def _release_reserved_run_locked(self, job_id: str) -> None:
        """Clear bookkeeping for a run that has been fully handled."""
        self._executing_job_ids.discard(job_id)
        self._reserved_runs.pop(job_id, None)

    def _abort_reserved_runs(self, reason: str) -> None:
        """Fail unresolved runs and clear in-memory bookkeeping immediately."""
        stop_error = CronServiceStoppingError(reason)
        reserved_runs = list(self._reserved_runs.values())
        self._reserved_runs.clear()
        self._executing_job_ids.clear()
        self._running_job_ids.clear()
        self._applying_job_ids.clear()

        for queued_run in reserved_runs:
            future = queued_run.completion_future
            if future is not None and not future.done():
                future.set_exception(stop_error)

    async def _apply_completed_run(self, completed_run: _CompletedRun) -> None:
        """Apply one finished run back onto the store and settle its manual future."""
        job_id = completed_run.result.job_id
        manual_future = completed_run.queued_run.completion_future
        manual_result = _manual_result_from_execution(completed_run.result)
        manual_error: Exception | None = None

        try:
            async with self._store_lock:
                store = await self._load_store_locked()
                can_merge_pending_store = self._can_merge_into_pending_store_locked()
                if not can_merge_pending_store:
                    self._require_store_available_locked()
                store = self._store if self._store is not None else store
                working_store = self._copy_store(store)
                self._recompute_next_runs_locked(working_store, preserve_existing=True)
                self._apply_execution_result_locked(working_store, completed_run.result)
                await self._commit_store_locked(
                    working_store,
                    allow_existing_error=can_merge_pending_store,
                    keep_memory_on_failure=True,
                )
        except CronStoreError as exc:
            if completed_run.queued_run.source == "manual":
                manual_error = exc
            else:
                logger.warning(
                    "Cron: background result sync failed for job %s; scheduler will retry once the store is healthy",
                    job_id,
                )
        finally:
            async with self._store_lock:
                self._release_reserved_run_locked(job_id)

            if manual_future is not None and not manual_future.done():
                if manual_error is not None:
                    manual_future.set_exception(manual_error)
                else:
                    manual_future.set_result(manual_result)

            self._applying_job_ids.discard(job_id)
            self._arm_timer()

    def _get_store_mtime(self) -> int | None:
        """Read the current store file modification time in nanoseconds, if it exists."""
        try:
            return self.store_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _read_store_from_disk(self) -> tuple[CronStore, int | None]:
        """Read and deserialize the persisted cron store."""
        with open(self.store_path, encoding="utf-8") as f:
            data = json.load(f)

        jobs = [CronJob.from_dict(job) for job in data.get("jobs", [])]
        store = CronStore(version=data.get("version", 1), jobs=jobs)
        return store, self._get_store_mtime()

    def _write_store_to_disk(self, store: CronStore) -> int | None:
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

    def _copy_store(self, store: CronStore) -> CronStore:
        """Create an isolated store snapshot so writes are transactional."""
        return CronStore(version=store.version, jobs=[self._copy_job(job) for job in store.jobs])

    def _set_store_error_locked(self, message: str, current_mtime: int | None) -> bool:
        """Record the latest store error and report whether it changed."""
        changed = self._store_error != message or self._store_error_mtime != current_mtime
        self._store_error = message
        self._store_error_mtime = current_mtime
        return changed

    def _clear_store_error_locked(self) -> None:
        """Clear any store error once disk state is readable again."""
        self._store_error = None
        self._store_error_action = None
        self._store_error_mtime = None

    def _mark_store_error_locked(self, action: str, current_mtime: int | None, exc: Exception) -> str:
        """Capture an actionable store error without discarding last known-good state."""
        message = f"Failed to {action} cron store at {self.store_path}: {exc}"
        self._store_error_action = action
        if self._set_store_error_locked(message, current_mtime):
            logger.exception(message)
        return message

    def _mark_missing_store_error_locked(self) -> str:
        """Capture an actionable error when a previously persisted store disappears."""
        return self._mark_store_error_locked(
            "load",
            None,
            FileNotFoundError(f"{self.store_path} is missing"),
        )

    def _require_store_available_locked(self) -> None:
        """Reject unsafe operations while the latest on-disk state is unreadable."""
        if self._store_error is not None:
            raise CronStoreUnavailableError(self._store_error)

    def _can_merge_into_pending_store_locked(self) -> bool:
        """Return whether a save-failed in-memory snapshot can accept more completed results."""
        return self._store_sync_pending and self._store is not None and self._store_error_action == "save"

    async def _ensure_store_writable_locked(self) -> None:
        """Retry pending persistence before allowing new writes or executions."""
        if self._store_sync_pending:
            if self._store is None:
                raise CronStoreUnavailableError("Cron store has pending in-memory state but no loaded snapshot")
            await self._commit_store_locked(
                self._copy_store(self._store),
                allow_existing_error=True,
                keep_memory_on_failure=True,
            )
        self._require_store_available_locked()

    async def _load_store_locked(self) -> CronStore:
        """Load store from disk, with hot-reload detection."""
        try:
            current_mtime = await asyncio.to_thread(self._get_store_mtime)
        except Exception as exc:
            message = self._mark_store_error_locked("stat", self._last_mtime, exc)
            if self._store is None:
                raise CronStoreUnavailableError(message) from exc
            return self._store

        if self._store_sync_pending:
            if self._store is None:
                raise CronStoreUnavailableError("Cron store has pending in-memory state but no loaded snapshot")
            return self._store

        if current_mtime is None:
            if self._last_mtime is not None:
                message = self._mark_missing_store_error_locked()
                if self._store is None:
                    raise CronStoreUnavailableError(message)
                return self._store

            if self._store is None:
                self._store = CronStore()
            self._last_mtime = None
            self._clear_store_error_locked()
            return self._store

        should_reload = self._store is None or current_mtime != self._last_mtime or self._store_error is not None
        if not should_reload:
            return self._store

        try:
            loaded_store, loaded_mtime = await asyncio.to_thread(self._read_store_from_disk)
        except Exception as exc:
            message = self._mark_store_error_locked("load", current_mtime, exc)
            if self._store is None:
                raise CronStoreUnavailableError(message) from exc
            return self._store

        if self._store is not None and current_mtime != self._last_mtime:
            logger.info("Cron: jobs.json modified externally, reloading")

        self._store = loaded_store
        self._last_mtime = loaded_mtime
        self._clear_store_error_locked()

        return self._store

    async def _commit_store_locked(
        self,
        store: CronStore,
        *,
        allow_existing_error: bool = False,
        keep_memory_on_failure: bool = False,
    ) -> None:
        """Persist a prepared store and commit it to memory only on success."""
        if not allow_existing_error:
            self._require_store_available_locked()
        try:
            new_mtime = await asyncio.to_thread(self._write_store_to_disk, store)
        except Exception as exc:
            if keep_memory_on_failure:
                self._store = store
                self._store_sync_pending = True
            message = self._mark_store_error_locked("save", self._last_mtime, exc)
            raise CronStorePersistenceError(message) from exc

        self._store = store
        self._last_mtime = new_mtime
        self._store_sync_pending = False
        self._clear_store_error_locked()

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

        times = [job.state.next_run_at_ms for job in active_store.jobs if job.id not in self._executing_job_ids and job.enabled and job.state.next_run_at_ms]
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

    def _build_unexpected_execution_result(self, job: CronJob, exc: Exception) -> _JobExecutionResult:
        """Convert an unexpected worker failure into a normal execution result."""
        start_ms = _now_ms()
        scheduled_run_at_ms = job.state.next_run_at_ms
        if job.schedule.kind == "at":
            next_run_at_ms = None
        else:
            cadence_anchor_ms = scheduled_run_at_ms if scheduled_run_at_ms is not None and scheduled_run_at_ms <= start_ms else start_ms
            next_run_at_ms = _compute_next_run(
                job.schedule,
                _now_ms(),
                anchor_ms=cadence_anchor_ms,
            )

        return _JobExecutionResult(
            job_id=job.id,
            last_run_at_ms=start_ms,
            next_run_at_ms=next_run_at_ms,
            last_status="error",
            last_error=str(exc),
        )

    async def _worker_loop(self) -> None:
        """Execute reserved jobs in the background without touching the store."""
        run_queue = self._run_queue
        result_queue = self._result_queue
        assert run_queue is not None
        assert result_queue is not None

        while True:
            queued_run = await run_queue.get()
            try:
                self._running_job_ids.add(queued_run.job.id)
                try:
                    execution_result = await self._execute_job(queued_run.job)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Cron: worker crashed while executing job %s", queued_run.job.id)
                    execution_result = self._build_unexpected_execution_result(queued_run.job, exc)

                if queued_run.generation != self._background_generation or self._hard_stop_requested:
                    continue

                await result_queue.put(
                    _CompletedRun(
                        queued_run=queued_run,
                        result=execution_result,
                    )
                )
            finally:
                self._running_job_ids.discard(queued_run.job.id)
                run_queue.task_done()

    async def _result_writer_loop(self) -> None:
        """Apply completed execution results back onto the store in a single place."""
        result_queue = self._result_queue
        assert result_queue is not None

        while True:
            completed_run = await result_queue.get()
            try:
                if completed_run.queued_run.generation != self._background_generation or self._hard_stop_requested:
                    continue

                self._applying_job_ids.add(completed_run.result.job_id)
                apply_task = asyncio.create_task(self._apply_completed_run(completed_run))
                try:
                    await asyncio.shield(apply_task)
                except asyncio.CancelledError:
                    if self._hard_stop_requested:
                        apply_task.cancel()
                        await asyncio.gather(apply_task, return_exceptions=True)
                    else:
                        await apply_task
                    raise
            finally:
                result_queue.task_done()

    async def start(self) -> None:
        """Start the cron service."""
        async with self._store_lock:
            if self._running:
                logger.warning("CronService already running")
                return
            self._raise_if_store_quarantined()
            self._prune_background_processors()
            if self._shutting_down and (self._worker_tasks or self._result_writer_task is not None or self._store_sync_pending):
                raise RuntimeError("CronService shutdown is still in progress")

            self._shutting_down = False
            self._hard_stop_requested = False
            self._background_generation += 1
            self._run_queue = asyncio.Queue()
            self._result_queue = asyncio.Queue()
            store = await self._load_store_locked()
            working_store = self._copy_store(store)
            self._recompute_next_runs_locked(working_store, preserve_existing=True)
            self._store = working_store
            self._ensure_background_processors_locked()
            self._running = True
            job_count = len(working_store.jobs)

        self._arm_timer()
        logger.info(f"CronService started with {job_count} jobs")

    def stop(self) -> None:
        """Stop the cron service immediately without draining background work."""
        should_quarantine_store = bool(self._applying_job_ids)
        self._running = False
        self._accepting_new_runs = False
        self._shutting_down = True
        self._hard_stop_requested = True
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        run_queue = self._run_queue
        result_queue = self._result_queue
        self._request_cancel_background_processors()
        self._drain_queue_nowait(run_queue)
        self._drain_queue_nowait(result_queue)
        self._run_queue = None
        self._result_queue = None
        self._abort_reserved_runs("CronService stopped before queued work could finish")
        if should_quarantine_store:
            self._quarantine_store(f"Cron store at {self.store_path} is quarantined after a hard stop during result persistence; restart the process before starting cron again for this store")
        logger.info("CronService stopped")

    async def shutdown(self, *, drain_timeout_s: float = 5.0) -> None:
        """Gracefully stop accepting new runs and persist completed work before stopping."""
        self._running = False
        self._accepting_new_runs = False
        self._shutting_down = True
        self._hard_stop_requested = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

        queues_drained = False
        try:
            async with asyncio.timeout(drain_timeout_s):
                if self._run_queue is not None:
                    await self._run_queue.join()
                if self._result_queue is not None:
                    await self._result_queue.join()
                queues_drained = True
                async with self._store_lock:
                    await self._ensure_store_writable_locked()
        except TimeoutError:
            logger.warning(
                "CronService shutdown timed out after %.1fs while waiting for graceful drain",
                drain_timeout_s,
            )
            self.stop()
            raise CronServiceShutdownTimeoutError(f"CronService shutdown timed out after {drain_timeout_s:.1f}s") from None
        finally:
            if queues_drained:
                await self._cancel_background_processors(timeout_s=None)
                self._run_queue = None
                self._result_queue = None
                logger.info("CronService shutdown complete")

    def _arm_timer(self) -> None:
        """Set the timer for the next wake-up."""
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

        if not self._running:
            return

        if self._store_error is not None:
            delay_s = self._store_retry_delay_s
        else:
            next_wake = self._get_next_wake_ms_locked()
            if not next_wake:
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
        if self._shutting_down:
            return
        due_jobs: list[CronJob] = []
        try:
            async with self._store_lock:
                store = await self._load_store_locked()
                await self._ensure_store_writable_locked()
                store = self._store if self._store is not None else store

                working_store = self._copy_store(store)
                self._recompute_next_runs_locked(working_store, preserve_existing=True)
                now = _now_ms()
                due_jobs = [self._copy_job(job) for job in working_store.jobs if (job.id not in self._executing_job_ids and job.enabled and job.state.next_run_at_ms and now >= job.state.next_run_at_ms)]
                if not due_jobs:
                    await self._commit_store_locked(working_store, keep_memory_on_failure=True)
                    return

                self._ensure_background_processors_locked()
                queued_runs = [_QueuedRun(job=job, source="timer", generation=self._background_generation) for job in due_jobs]
                for queued_run in queued_runs:
                    self._reserve_run_locked(queued_run)

            run_queue = self._run_queue
            if run_queue is None or self._shutting_down:
                return
            for queued_run in queued_runs:
                if queued_run.generation != self._background_generation or self._hard_stop_requested:
                    break
                run_queue.put_nowait(queued_run)
        except CronStoreError:
            logger.warning("Cron: timer run paused until cron store becomes healthy again")
        finally:
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
            cadence_anchor_ms = scheduled_run_at_ms if scheduled_run_at_ms is not None and scheduled_run_at_ms <= start_ms else start_ms
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
        normalize_cron_schedule_timezone(schedule)
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
            await self._ensure_store_writable_locked()
            store = self._store if self._store is not None else store
            working_store = self._copy_store(store)
            working_store.jobs.append(self._copy_job(job))
            await self._commit_store_locked(working_store)

        self._arm_timer()

        logger.info(f"Cron: added job '{name}' ({job.id}), next run at {job.state.next_run_at_ms}")
        return job

    async def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        removed = False
        async with self._store_lock:
            store = await self._load_store_locked()
            await self._ensure_store_writable_locked()
            store = self._store if self._store is not None else store
            working_store = self._copy_store(store)
            for i, job in enumerate(working_store.jobs):
                if job.id == job_id:
                    del working_store.jobs[i]
                    await self._commit_store_locked(working_store)
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
            await self._ensure_store_writable_locked()
            store = self._store if self._store is not None else store
            working_store = self._copy_store(store)
            for job in working_store.jobs:
                if job.id == job_id:
                    if enabled:
                        next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                        if next_run_at_ms is None:
                            raise NoFutureRunTimeError(f"Job {job_id} cannot be enabled because its schedule has no future run time")
                        job.enabled = True
                        job.state.next_run_at_ms = next_run_at_ms
                    else:
                        job.enabled = False
                        job.state.next_run_at_ms = None
                    await self._commit_store_locked(working_store)
                    updated = True
                    break

        if updated:
            self._arm_timer()
            logger.info(f"Cron: {'enabled' if enabled else 'disabled'} job {job_id}")
        return updated

    async def run_job(self, job_id: str, force: bool = True) -> _ManualRunResult | None:
        """Manually trigger a job.

        Args:
            job_id: Job ID to run
            force: Run even if disabled

        Returns:
            Manual run outcome, or None if not found
        """
        if self._shutting_down:
            raise CronServiceStoppingError("CronService is shutting down")
        queued_run: _QueuedRun | None = None
        run_queue: asyncio.Queue[_QueuedRun] | None = None
        async with self._store_lock:
            store = await self._load_store_locked()
            await self._ensure_store_writable_locked()
            store = self._store if self._store is not None else store
            for job in store.jobs:
                if job.id != job_id or not (job.enabled or force):
                    continue
                if job.id in self._executing_job_ids:
                    return _ManualRunResult(status="ignored", result="already_running")

                self._ensure_background_processors_locked()
                queued_run = _QueuedRun(
                    job=self._copy_job(job),
                    source="manual",
                    generation=self._background_generation,
                    completion_future=asyncio.get_running_loop().create_future(),
                )
                run_queue = self._run_queue
                self._reserve_run_locked(queued_run)
                break
            else:
                return None

        if run_queue is None or queued_run.generation != self._background_generation or self._shutting_down or self._hard_stop_requested:
            stop_error = CronServiceStoppingError("CronService is shutting down")
            if not queued_run.completion_future.done():
                queued_run.completion_future.set_exception(stop_error)
            raise stop_error

        assert queued_run is not None
        run_queue.put_nowait(queued_run)
        try:
            return await queued_run.completion_future
        finally:
            self._arm_timer()

    async def status(self) -> dict:
        """Get service status."""
        async with self._store_lock:
            store = await self._load_store_locked()
            jobs = list(store.jobs)

        enabled = sum(1 for j in jobs if j.enabled)
        queued_runs = self._run_queue.qsize() if self._run_queue is not None else 0
        queued_result_writes = self._result_queue.qsize() if self._result_queue is not None else 0
        applying_result_writes = len(self._applying_job_ids)
        return {
            "running": self._running,
            "jobs": len(jobs),
            "enabled": enabled,
            "disabled": len(jobs) - enabled,
            "executing_jobs": len(self._running_job_ids),
            "inflight_runs": len(self._executing_job_ids),
            "queued_runs": queued_runs,
            "queued_result_writes": queued_result_writes,
            "applying_result_writes": applying_result_writes,
            "pending_result_writes": queued_result_writes + applying_result_writes,
            "max_concurrent_runs": self._max_concurrent_runs,
            "store_available": self._store_error is None,
            "store_error": self._store_error,
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

    service = CronService(store_path=store_path, on_job=on_job)
    await service.start()
    _cron_service = service
    return service


async def stop_cron_service_async(*, drain_timeout_s: float = 5.0) -> None:
    """Gracefully stop the global CronService and wait for queued work to settle."""
    global _cron_service
    if _cron_service is not None:
        service = _cron_service
        try:
            await service.shutdown(drain_timeout_s=drain_timeout_s)
        finally:
            _cron_service = None


def stop_cron_service() -> None:
    """Stop the global CronService immediately without draining background work."""
    global _cron_service
    if _cron_service is not None:
        _cron_service.stop()
        _cron_service = None
