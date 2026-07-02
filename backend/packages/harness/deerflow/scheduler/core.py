"""Asyncio scheduler loop that owns the in-memory job table.

The scheduler is the heart of the ``scheduled_jobs`` feature. It runs a
1-second tick loop that:

1. Queries ``ScheduledJobRepository.list_due_jobs`` for everything with
   ``next_run_at <= now``.
2. Spawns a bounded coroutine per due job (``Semaphore`` cap).
3. Each coroutine calls the injected ``JobExecutor.execute`` (which
   lives in ``app.scheduled_jobs`` and is responsible for user-context
   setup + Agent invocation + delivery).
4. After execution, recomputes ``next_run_at`` (and applies error
   backoff if the run failed), then persists via the repository.

Design constraints:

- **No imports from ``app.*``**: this module lives in the harness layer.
  The executor is injected by the application layer at startup.
- **Crash-safe**: all scheduling state lives in SQLite. The in-memory
  ``_jobs`` dict is just a cache for the tick loop. On restart,
  ``_load_jobs_from_db`` rebuilds it.
- **No thundering herd on restart**: missed ``at`` runs are marked
  skipped (not replayed); recurring jobs recompute the next slot from
  ``now``.
- **Per-job isolation**: if one job's executor raises, others continue
  unaffected (``asyncio.create_task`` + try/except per job).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from deerflow.persistence.scheduled_jobs import ScheduledJobRepository
from deerflow.scheduler.retry import error_backoff_delay
from deerflow.scheduler.triggers import (
    AtTrigger,
    Trigger,
    trigger_from_persisted,
)
from deerflow.utils.time import coerce_datetime

logger = logging.getLogger(__name__)


# Hard cap on concurrent job executions across the whole scheduler.
DEFAULT_MAX_CONCURRENT: int = 8

# Hard timeout for a single job execution. The executor may impose a
# tighter per-job timeout; this is the scheduler backstop.
DEFAULT_JOB_TIMEOUT_SECONDS: int = 300  # 5 minutes


@dataclass
class ExecutionResult:
    """Result returned by ``JobExecutor.execute``.

    ``status`` is one of ``"ok"``, ``"error"``, ``"skipped"``.
    """

    status: str
    thread_id: str | None = None
    error_msg: str | None = None
    token_usage: int = 0
    duration_ms: int = 0


class JobExecutor(Protocol):
    """Application-layer executor. Constructed in ``app.scheduled_jobs``
    and injected into the Scheduler at lifespan startup.

    Implementations are responsible for:

    - Setting up user context (``set_current_user(job["user_id"])``)
    - Invoking the Agent (``DeerFlowClient.chat``)
    - Persisting a run record
    - Delivering the result to the source channel
    """

    async def execute(self, job: dict[str, Any]) -> ExecutionResult: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _trigger_from_job(job: dict[str, Any]) -> Trigger:
    """Reconstruct a Trigger from a job row dict."""
    return trigger_from_persisted(
        trigger_type=job["trigger_type"],
        trigger_data=job["trigger_data"] if isinstance(job["trigger_data"], dict) else {},
    )


class Scheduler:
    """In-process asyncio scheduler.

    Construct once at application startup (in the Gateway lifespan) and
    call ``start``. Stopping is graceful: ``stop`` cancels the tick loop
    but does not abort in-flight executions.
    """

    def __init__(
        self,
        repo: ScheduledJobRepository,
        executor: JobExecutor,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        job_timeout_seconds: int = DEFAULT_JOB_TIMEOUT_SECONDS,
        tick_interval_seconds: float = 1.0,
    ) -> None:
        self._repo = repo
        self._executor = executor
        self._max_concurrent = max_concurrent
        self._job_timeout_seconds = job_timeout_seconds
        self._tick_interval = tick_interval_seconds

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()  # guards mutations to _inflight
        self._inflight: set[str] = set()  # job_ids currently executing

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load jobs from DB and start the tick loop. Idempotent."""
        if self._task is not None:
            return
        await self._recover_missed_runs()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="deerflow-scheduler-tick")
        logger.info("scheduler started (max_concurrent=%d)", self._max_concurrent)

    async def stop(self) -> None:
        """Signal the tick loop to exit. Waits for it to drain."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except TimeoutError:
            logger.warning("scheduler tick loop did not exit cleanly, cancelling")
            self._task.cancel()
        self._task = None
        logger.info("scheduler stopped")

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    async def _recover_missed_runs(self) -> None:
        """On startup, find jobs whose ``next_run_at`` is in the past and
        either:

        - mark them skipped (one-shot ``at`` jobs that missed their window)
        - recompute the next slot (recurring jobs)

        We do NOT replay missed runs — that would cause a thundering herd
        after a Gateway restart with many stale jobs.
        """
        now = _utc_now()
        due = await self._repo.list_all_enabled_jobs()
        skipped = 0
        rescheduled = 0
        for job in due:
            next_run_at = coerce_datetime(job.get("next_run_at"))
            if next_run_at is None or next_run_at > now:
                continue

            trigger = _trigger_from_job(job)
            if isinstance(trigger, AtTrigger):
                # Missed one-shot: mark disabled so it stops appearing in
                # list_due_jobs. The repository row is preserved (audit).
                await self._repo.update_scheduling_state(
                    job["id"],
                    enabled=False,
                    last_status="skipped",
                    user_id=None,  # admin scope — scheduler is cross-user
                )
                skipped += 1
                continue

            new_next = trigger.compute_next(now, now=now, job_id=job["id"])
            if new_next is None:
                # Should not happen for recurring triggers, but be safe.
                await self._repo.disable_job(job["id"], user_id=None)
                continue
            await self._repo.update_scheduling_state(
                job["id"],
                next_run_at=new_next,
                user_id=None,
            )
            rescheduled += 1

        if skipped or rescheduled:
            logger.info(
                "scheduler recovery: %d one-shot skipped, %d recurring rescheduled",
                skipped,
                rescheduled,
            )

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Tick every ``tick_interval`` seconds until ``stop`` is called."""
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_interval)
            except TimeoutError:
                continue

    async def _tick(self) -> None:
        """Find due jobs and dispatch each in its own task."""
        now = _utc_now()
        due = await self._repo.list_due_jobs(now=now)
        if not due:
            return

        for job in due:
            job_id = job["id"]
            async with self._lock:
                if job_id in self._inflight:
                    # Previous execution still running — skip this slot.
                    continue
                self._inflight.add(job_id)
            # Optimistically bump next_run_at so subsequent ticks don't
            # re-pick this job while it's running. The executor will
            # overwrite this with the real value after completion.
            trigger = _trigger_from_job(job)
            # Anchor the next slot on the time this run was *scheduled*
            # to fire (job["next_run_at"]), not the current tick time.
            # For unanchored ``every`` jobs this keeps the cadence strict
            # instead of drifting by the execution duration each cycle;
            # for ``cron``/anchored triggers the result is identical.
            # This value also stands in as the fallback next_run_at if
            # ``_finalise`` later fails to persist (see _run_job_safely).
            fired_at = coerce_datetime(job.get("next_run_at")) or now
            tentative_next = trigger.compute_next(fired_at, now=now, job_id=job_id)
            if tentative_next is not None:
                await self._repo.update_scheduling_state(
                    job_id,
                    next_run_at=tentative_next,
                    user_id=None,
                )
            asyncio.create_task(self._run_job_safely(job))

    async def _run_job_safely(self, job: dict[str, Any]) -> None:
        """Wrap a single job execution with concurrency limit, timeout,
        and exception isolation.
        """
        job_id = job["id"]
        async with self._semaphore:
            started_at = _utc_now()
            try:
                result = await asyncio.wait_for(
                    self._executor.execute(job),
                    timeout=self._job_timeout_seconds,
                )
                await self._finalise(job, result, started_at)
            except TimeoutError:
                logger.warning("job %s timed out after %ds", job_id, self._job_timeout_seconds)
                await self._finalise(
                    job,
                    ExecutionResult(
                        status="timeout",
                        error_msg=f"timed out after {self._job_timeout_seconds}s",
                        duration_ms=int((_utc_now() - started_at).total_seconds() * 1000),
                    ),
                    started_at,
                )
            except Exception as exc:
                logger.exception("job %s executor raised", job_id)
                await self._finalise(
                    job,
                    ExecutionResult(
                        status="error",
                        error_msg=str(exc),
                        duration_ms=int((_utc_now() - started_at).total_seconds() * 1000),
                    ),
                    started_at,
                )
            finally:
                async with self._lock:
                    self._inflight.discard(job_id)

    async def _finalise(
        self,
        job: dict[str, Any],
        result: ExecutionResult,
        started_at: datetime,
    ) -> None:
        """After execution, update scheduling state and recompute next run.

        Delegates to ``_persist_run_outcome`` for the actual logic.
        Persistence here is **best-effort**: if the repo write raises,
        the exception is logged and swallowed so the tick loop and
        sibling jobs are unaffected. The job's ``next_run_at`` already
        holds the optimistic tentative value from ``_tick``, so the job
        simply fires again on that slot; on the next scheduler start
        ``_recover_missed_runs`` recomputes any slot that drifted into
        the past. This avoids the previous failure mode where a raised
        ``_finalise`` was re-invoked with an ``error`` status by
        ``_run_job_safely``'s except branch (double-counting failures
        and leaving ``last_status`` stale).
        """
        job_id = job["id"]
        try:
            await self._persist_run_outcome(job, result)
        except Exception:
            logger.exception(
                "job %s: failed to persist scheduling state after run (status=%s); next_run_at keeps its tentative value and self-heals on the next slot or restart",
                job_id,
                result.status,
            )

    async def _persist_run_outcome(
        self,
        job: dict[str, Any],
        result: ExecutionResult,
    ) -> None:
        """Compute and write the post-run scheduling state. May raise.

        Logic:

        - ``ok`` / ``skipped``: reset consecutive_errors, no retry slot
        - ``error`` / ``timeout``: increment consecutive_errors, schedule
          a retry slot via exponential backoff
        - One-shot ``at`` job: if ``delete_after_run``, hard-delete;
          otherwise disable
        - Recurring job: compute next natural slot; if a retry slot is
          active, take the earlier of the two
        """
        job_id = job["id"]
        now = _utc_now()
        trigger = _trigger_from_job(job)
        is_one_shot = isinstance(trigger, AtTrigger)

        # Compute new error counter
        current_errors = int(job.get("consecutive_errors") or 0)
        if result.status in ("error", "timeout"):
            new_errors = current_errors + 1
            retry_at = now + error_backoff_delay(new_errors)
        else:
            new_errors = 0
            retry_at = None

        # Compute natural next slot (None for one-shot after firing).
        # Anchor on the slot that just fired (job["next_run_at"]), not
        # the finish time — otherwise unanchored ``every`` jobs drift by
        # their execution duration every cycle.
        fired_at = coerce_datetime(job.get("next_run_at")) or now
        natural_next = trigger.compute_next(fired_at, now=now, job_id=job_id)

        # One-shot handling
        if is_one_shot and natural_next is None:
            delete_after = bool(job.get("delete_after_run"))
            if delete_after:
                await self._repo.delete_job(job_id, user_id=None)
                logger.info("one-shot job %s auto-deleted after run", job_id)
            else:
                await self._repo.update_scheduling_state(
                    job_id,
                    enabled=False,
                    last_run_at=now,
                    last_status=result.status,
                    consecutive_errors=new_errors,
                    user_id=None,
                )
            return

        # Recurring: pick the earlier of natural_next and retry_at
        candidates = [dt for dt in (natural_next, retry_at) if dt is not None]
        next_run_at = min(candidates) if candidates else now + timedelta(minutes=1)

        await self._repo.update_scheduling_state(
            job_id,
            next_run_at=next_run_at,
            last_run_at=now,
            last_status=result.status,
            consecutive_errors=new_errors,
            next_retry_at=retry_at,
            user_id=None,
        )
