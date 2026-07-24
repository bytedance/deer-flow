from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException

from deerflow.persistence.scheduled_task_runs import ActiveScheduledRunConflict
from deerflow.runtime import ConflictError, RunRecord
from deerflow.scheduler.schedules import next_run_at

logger = logging.getLogger(__name__)

# Shared so the has_active_runs fast path and the unique-index race path return
# byte-identical outcomes for the same "task already has an active run" condition.
_ACTIVE_RUN_CONFLICT_ERROR = "task already has an active run"
_SKIP_ACTIVE_RUN_ERROR = "skipped: a previous run of this task is still active"


class ScheduledTaskService:
    def __init__(
        self,
        *,
        task_repo,
        task_run_repo,
        launch_run,
        poll_interval_seconds: int,
        lease_seconds: int,
        max_concurrent_runs: int,
    ) -> None:
        self._task_repo = task_repo
        self._task_run_repo = task_run_repo
        self._launch_run = launch_run
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_runs = max_concurrent_runs
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def run_once(self, *, now: datetime) -> None:
        # ``max_concurrent_runs`` is a global cap on active scheduled runs, not
        # just a per-poll claim batch: long runs accumulate across poll cycles,
        # so each cycle only claims into the remaining budget.
        active = await self._task_run_repo.count_active_runs()
        budget = self._max_concurrent_runs - active
        if budget <= 0:
            return
        claimed = await self._task_repo.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=budget,
        )
        for task in claimed:
            await self.dispatch_task(task, now=now, trigger="scheduled")

    @staticmethod
    def _is_overlap_conflict(exc: Exception) -> bool:
        if isinstance(exc, ConflictError):
            return True
        return isinstance(exc, HTTPException) and exc.status_code == 409

    @staticmethod
    def _task_status_for_failure(task: dict[str, Any], *, trigger: str) -> str:
        if trigger == "manual":
            # A failed manual trigger must not consume the task's scheduled
            # future: a `once` task with run_at still ahead would otherwise be
            # flipped to "failed" and never claimed again.
            return task.get("status") or "enabled"
        if task["schedule_type"] == "once":
            return "failed"
        return "enabled"

    @staticmethod
    def _task_status_for_skip(task: dict[str, Any]) -> str:
        if task["schedule_type"] == "once":
            # The single occurrence was lost to an overlapping run; "completed"
            # would claim an execution that never happened.
            return "failed"
        return "enabled"

    async def dispatch_task(
        self,
        task: dict[str, Any],
        *,
        now: datetime,
        trigger: str,
    ) -> dict[str, Any]:
        execution_thread_id = task.get("thread_id")
        if task.get("context_mode") == "fresh_thread_per_run" or not execution_thread_id:
            execution_thread_id = str(uuid.uuid4())
        # "skip" must hold for fresh-thread runs too, where every run gets a new
        # thread and the same-thread multitask ConflictError below can never
        # fire. Checked before creating this dispatch's own run row so the row
        # does not count itself as the active run. A manual trigger against an
        # active run is rejected outright (409 at the router) instead of being
        # recorded as a skipped occurrence — nothing was scheduled to happen.
        #
        # This has_active_runs check is a non-atomic fast path: it runs in its
        # own session and is separated from the create() below by await points,
        # so two concurrent dispatches (double-click / client retry / a manual
        # trigger racing the poller) can both observe no active run. The DB is
        # the atomic arbiter — the partial unique index uq_scheduled_task_run_active
        # rejects the second active insert, surfaced as ActiveScheduledRunConflict
        # and collapsed to the SAME outcome as this fast path just below.
        overlap_skip = task.get("overlap_policy", "skip") == "skip"
        if overlap_skip and await self._task_run_repo.has_active_runs(task["id"]):
            if trigger == "manual":
                return self._active_run_conflict_result(execution_thread_id)
            return await self._record_scheduled_skip(task, thread_id=execution_thread_id, now=now, trigger=trigger)

        task_run_id = f"task-run-{uuid.uuid4().hex}"
        try:
            await self._task_run_repo.create(
                run_record_id=task_run_id,
                task_id=task["id"],
                thread_id=execution_thread_id,
                scheduled_for=now,
                trigger=trigger,
                status="queued",
            )
        except ActiveScheduledRunConflict:
            # Lost the create race for the task's single active slot: a
            # concurrent dispatch passed the same fast-path check and inserted
            # its active row first. Identical outcome to the fast path above.
            if trigger == "manual":
                return self._active_run_conflict_result(execution_thread_id)
            return await self._record_scheduled_skip(task, thread_id=execution_thread_id, now=now, trigger=trigger)
        try:
            result = await self._launch_run(
                thread_id=execution_thread_id,
                assistant_id=task.get("assistant_id"),
                prompt=task["prompt"],
                owner_user_id=task.get("user_id"),
                metadata={
                    "scheduled_task_id": task["id"],
                    "scheduled_task_run_id": task_run_id,
                    "scheduled_trigger": trigger,
                },
            )
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            if task["schedule_type"] == "once":
                # Stay "running" until handle_run_completion sees the real
                # terminal outcome; declaring "completed" at launch would stick
                # if the run fails or the process dies (startup reconciliation
                # is cancel_stuck_once_tasks).
                task_status = "running"
            elif trigger == "manual" and task.get("status") == "paused":
                task_status = "paused"
            else:
                task_status = "enabled"
            await self._task_run_repo.update_status(
                task_run_id,
                status="running",
                run_id=result["run_id"],
                started_at=now,
                # A fast-failing run can reach handle_run_completion before this
                # write resumes; never clobber its terminal status.
                protect_terminal=True,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=result["run_id"],
                last_thread_id=result["thread_id"],
                last_error=None,
                increment_run_count=True,
                # Same race as the run-row write above: a fast-failing run's
                # completion hook may have already finalized a `once` task.
                protect_terminal=True,
            )
            return {
                "outcome": "launched",
                "task_run_id": task_run_id,
                "run_id": result["run_id"],
                "thread_id": result["thread_id"],
                "error": None,
            }
        except Exception as exc:
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            if self._is_overlap_conflict(exc) and trigger == "scheduled" and task.get("overlap_policy", "skip") == "skip":
                return await self._finalize_skip(task, task_run_id=task_run_id, thread_id=execution_thread_id, now=now, error=str(exc))

            task_status = self._task_status_for_failure(task, trigger=trigger)
            await self._task_run_repo.update_status(
                task_run_id,
                status="failed",
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=None,
                last_thread_id=execution_thread_id,
                last_error=str(exc),
                increment_run_count=False,
            )
            return {
                "outcome": "conflict" if self._is_overlap_conflict(exc) else "failed",
                "task_run_id": task_run_id,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": str(exc),
            }

    def _active_run_conflict_result(self, thread_id: str) -> dict[str, Any]:
        """Manual-trigger response when the task already has an active run.

        Nothing was scheduled to happen, so no run-history row is recorded; the
        router maps this to a 409.
        """
        return {
            "outcome": "conflict",
            "task_run_id": None,
            "run_id": None,
            "thread_id": thread_id,
            "error": _ACTIVE_RUN_CONFLICT_ERROR,
        }

    async def _record_scheduled_skip(
        self,
        task: dict[str, Any],
        *,
        thread_id: str,
        now: datetime,
        trigger: str,
    ) -> dict[str, Any]:
        """Record a skipped occurrence for a scheduled dispatch that overlapped an active run.

        The tombstone is created directly as terminal ``"skipped"`` rather than
        the transient ``"queued"`` the launch path uses: a queued row is active
        and would itself trip ``uq_scheduled_task_run_active`` against the
        pre-existing run that is still holding the task's single active slot.
        ``"skipped"`` is outside the index predicate, so it never conflicts.
        """
        task_run_id = f"task-run-{uuid.uuid4().hex}"
        await self._task_run_repo.create(
            run_record_id=task_run_id,
            task_id=task["id"],
            thread_id=thread_id,
            scheduled_for=now,
            trigger=trigger,
            status="skipped",
        )
        return await self._finalize_skip(task, task_run_id=task_run_id, thread_id=thread_id, now=now, error=_SKIP_ACTIVE_RUN_ERROR)

    async def _finalize_skip(
        self,
        task: dict[str, Any],
        *,
        task_run_id: str,
        thread_id: str,
        now: datetime,
        error: str,
    ) -> dict[str, Any]:
        next_at = next_run_at(
            task["schedule_type"],
            task["schedule_spec"],
            task["timezone"],
            now=now,
        )
        await self._task_run_repo.update_status(
            task_run_id,
            status="skipped",
            error=error,
            started_at=now,
            finished_at=now,
        )
        await self._task_repo.update_after_launch(
            task["id"],
            status=self._task_status_for_skip(task),
            next_run_at=next_at,
            last_run_at=task.get("last_run_at"),
            last_run_id=task.get("last_run_id"),
            last_thread_id=task.get("last_thread_id"),
            last_error=error if task["schedule_type"] == "once" else None,
            increment_run_count=False,
        )
        return {
            "outcome": "skipped",
            "task_run_id": task_run_id,
            "run_id": None,
            "thread_id": thread_id,
            "error": error,
        }

    async def handle_run_completion(self, record: RunRecord) -> None:
        metadata = record.metadata or {}
        task_id = metadata.get("scheduled_task_id")
        task_run_id = metadata.get("scheduled_task_run_id")
        user_id = record.user_id
        if not isinstance(task_id, str) or not isinstance(task_run_id, str) or not user_id:
            return

        terminal_status: Literal["success", "failed", "interrupted"] | None
        if record.status.value == "success":
            terminal_status = "success"
            error = None
        elif record.status.value == "interrupted":
            # Distinct from "failed": an interrupt (user cancel, same-thread
            # takeover) carries no error and is not an execution failure.
            terminal_status = "interrupted"
            error = record.error or "run was interrupted before completion"
        elif record.status.value in {"error", "timeout"}:
            terminal_status = "failed"
            error = record.error
        else:
            terminal_status = None
            error = record.error
        if terminal_status is None:
            return

        await self._task_run_repo.update_status(
            task_run_id,
            status=terminal_status,
            run_id=record.run_id,
            error=error,
            finished_at=datetime.now(UTC),
        )

        task = await self._task_repo.get(task_id, user_id=user_id)
        if task is None:
            return

        updates: dict[str, Any] = {"last_error": error}
        if task["schedule_type"] == "once":
            # The single occurrence is consumed either way (the run did launch,
            # so re-arming risks duplicate side effects), but an interrupt ends
            # as "cancelled", not "failed".
            if terminal_status == "success":
                updates["status"] = "completed"
            elif terminal_status == "interrupted":
                updates["status"] = "cancelled"
            else:
                updates["status"] = "failed"
        await self._task_repo.update(task_id, user_id=user_id, updates=updates)

    async def start(self) -> None:
        if self._task is not None:
            return
        restart_error = "interrupted: gateway restarted before the run reached a terminal state"
        try:
            stale = await self._task_run_repo.mark_stale_active_runs(error=restart_error)
            if stale:
                logger.warning("Marked %d stale scheduled task run(s) as interrupted after restart", stale)
        except Exception:
            logger.exception("Failed to sweep stale scheduled task runs at startup")
        try:
            # The run rows above are only half the story: a launched `once`
            # task is parked in "running" until the (now dead) completion hook
            # would have finalized it, so reconcile the parent rows too.
            stuck = await self._task_repo.cancel_stuck_once_tasks(error=restart_error)
            if stuck:
                logger.warning("Cancelled %d stuck once task(s) after restart", stuck)
        except Exception:
            logger.exception("Failed to reconcile stuck once tasks at startup")
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once(now=datetime.now(UTC))
            except Exception:
                # A transient DB error (e.g. SQLite "database is locked") must
                # not kill the poller task for the rest of the process life.
                logger.exception("Scheduled task poll failed; retrying next interval")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue
