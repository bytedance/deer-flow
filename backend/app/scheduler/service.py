from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException

from deerflow.persistence.scheduled_task_runs import ActiveScheduledRunConflict, ScheduledTaskAdmissionRejected
from deerflow.runtime import ConflictError, RunRecord
from deerflow.scheduler.schedules import next_run_at
from deerflow.trace_context import ensure_trace_context
from deerflow.utils.thread_id import validate_thread_id

logger = logging.getLogger(__name__)

# Shared so the active-row fast path and the atomic-admission conflict path
# return byte-identical outcomes for the same active-occurrence condition.
_ACTIVE_RUN_CONFLICT_ERROR = "task already has an active run"
_RESTART_RECOVERY_ERROR = "interrupted: gateway restarted before the run reached a terminal state"
_LEASE_RECOVERY_ERROR = "interrupted: the owning gateway stopped renewing its run lease"
_QUEUE_TIMEOUT_ERROR = "scheduled task queue wait timeout exceeded"


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
        queue_timeout_seconds: int = 3600,
        multi_instance: bool = False,
        run_lease_grace_seconds: int = 10,
    ) -> None:
        self._task_repo = task_repo
        self._task_run_repo = task_run_repo
        self._launch_run = launch_run
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_runs = max_concurrent_runs
        self._queue_timeout_seconds = queue_timeout_seconds
        self._multi_instance = multi_instance
        self._run_lease_grace_seconds = run_lease_grace_seconds
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._skip_next_lease_reconciliation = False

    async def run_once(self, *, now: datetime) -> None:
        if self._multi_instance:
            if self._skip_next_lease_reconciliation:
                self._skip_next_lease_reconciliation = False
            else:
                await self._reconcile_active_state(now=now)
        else:
            await self._task_run_repo.recover_expired_launch_claims(
                error=_LEASE_RECOVERY_ERROR,
                now=now,
            )
        await self._expire_waiting_runs(now=now)
        await self._drain_queue(now=now)
        # Admission and execution capacity are separate. Due occurrences are
        # persisted even when all execution slots are busy; claim_queued_run()
        # applies the global launch budget under the database lock.
        claimed = await self._task_repo.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_runs,
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
    def _task_status_for_launch(task: dict[str, Any], *, trigger: str) -> str:
        # The task-level status to write once _launch_run has produced a live
        # run. A `once` task stays "running" until handle_run_completion
        # observes the real terminal outcome; declaring "completed" at launch
        # would stick if the run fails or the process dies (startup
        # reconciliation is cancel_stuck_once_tasks).
        if task["schedule_type"] == "once":
            return "running"
        if trigger == "manual" and task.get("status") == "paused":
            return "paused"
        return "enabled"

    async def dispatch_task(
        self,
        task: dict[str, Any],
        *,
        now: datetime,
        trigger: str,
    ) -> dict[str, Any]:
        expected_lease_owner = self._lease_owner if trigger == "scheduled" else None
        execution_thread_id = task.get("thread_id")
        if task.get("context_mode") == "fresh_thread_per_run" or execution_thread_id is None:
            execution_thread_id = str(uuid.uuid4())
        try:
            validate_thread_id(execution_thread_id)
        except ValueError as exc:
            # Rows persisted before the thread-id contract was centralized may
            # hold IDs that were valid then (dots, unlimited length) but fail
            # the canonical pattern now. Route through the normal failure
            # bookkeeping instead of raising: an uncaught ValueError here would
            # surface as HTTP 500 on manual trigger and, in the poller, abort
            # the rest of the claimed batch every cycle while the task itself
            # is never marked with last_error.
            task_status = self._task_status_for_failure(task, trigger=trigger)
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_run_at(
                    task["schedule_type"],
                    task["schedule_spec"],
                    task["timezone"],
                    now=now,
                ),
                last_run_at=now,
                last_run_id=None,
                last_thread_id=execution_thread_id,
                last_error=str(exc),
                increment_run_count=False,
                expected_lease_owner=expected_lease_owner,
            )
            return {
                "outcome": "failed",
                "task_run_id": None,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": str(exc),
            }
        active = await self._task_run_repo.get_active_run(task["id"])
        if active is not None:
            if trigger == "scheduled":
                await self._release_admission_lease(task, trigger=trigger)
            return self._existing_active_result(active, execution_thread_id, trigger=trigger)

        task_run_id = f"task-run-{uuid.uuid4().hex}"
        try:
            await self._task_run_repo.create(
                run_record_id=task_run_id,
                task_id=task["id"],
                thread_id=execution_thread_id,
                scheduled_for=now,
                trigger=trigger,
                status="queued",
                coordinate_with_task=True,
                expected_task_user_id=task.get("user_id"),
                expected_task_status=task.get("status") if trigger == "manual" else None,
                expected_task_updated_at=task.get("updated_at") if trigger == "manual" else None,
                expected_task_lease_owner=self._lease_owner if trigger == "scheduled" else None,
                release_task_lease_status="enabled" if trigger == "scheduled" else None,
            )
        except ActiveScheduledRunConflict:
            active = await self._task_run_repo.get_active_run(task["id"])
            if trigger == "scheduled":
                await self._release_admission_lease(task, trigger=trigger)
            if active is None:
                return self._active_run_conflict_result(execution_thread_id)
            return self._existing_active_result(active, execution_thread_id, trigger=trigger)
        except ScheduledTaskAdmissionRejected as exc:
            if exc.reason == "not_found":
                return {
                    "outcome": "not_found",
                    "task_run_id": None,
                    "run_id": None,
                    "thread_id": execution_thread_id,
                    "error": "scheduled task no longer exists",
                }
            return {
                "outcome": "conflict",
                "task_run_id": None,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": "scheduled task changed before trigger admission",
            }

        # Scheduled admission inserted the queue row and released its parent
        # lease in one transaction. Manual admission verified that this task
        # snapshot was still current under the same parent lock.
        queued = {
            "id": task_run_id,
            "task_id": task["id"],
            "thread_id": execution_thread_id,
            "trigger": trigger,
        }
        return await self._attempt_queued_run(task, queued, now=now)

    async def _release_admission_lease(self, task: dict[str, Any], *, trigger: str) -> None:
        status = "enabled" if trigger == "scheduled" else (task.get("status") or "enabled")
        await self._task_repo.release_dispatch_lease(
            task["id"],
            expected_lease_owner=self._lease_owner if trigger == "scheduled" else None,
            status=status,
        )

    async def _attempt_queued_run(
        self,
        task: dict[str, Any],
        queued: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        """Turn one queued occurrence into a live run under its own trace scope.

        The poller is a non-HTTP entry point, so no ``TraceMiddleware`` has
        bound anything: each occurrence opens its own scope rather than
        sharing one id across a whole poll cycle. A manual trigger arrives
        inside a Gateway request and keeps that request's trace instead, so
        the launched run stays correlated with the call that asked for it.
        """
        with ensure_trace_context():
            return await self._launch_queued_occurrence(task, queued, now=now)

    async def _launch_queued_occurrence(
        self,
        task: dict[str, Any],
        queued: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        task_run_id = queued["id"]
        execution_thread_id = queued["thread_id"]
        trigger = queued["trigger"]
        claimed = await self._task_run_repo.claim_queued_run(
            task_run_id,
            lease_owner=self._lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
            global_max_concurrent_runs=self._max_concurrent_runs,
        )
        if claimed is None:
            return self._queued_result(task_run_id, execution_thread_id)

        # Track whether _launch_run has produced a live run. A bookkeeping
        # failure after launch must retain the non-terminal slot so a later
        # poll cannot start the same occurrence twice.
        launched_run_id: str | None = None
        launched_thread_id: str | None = None
        launch_succeeded = False
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
            launch_succeeded = True
            launched_run_id = result["run_id"]
            launched_thread_id = result["thread_id"]
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            task_status = self._task_status_for_launch(task, trigger=trigger)
            await self._record_launched_run(
                task_run_id=task_run_id,
                task_id=task["id"],
                run_id=launched_run_id,
                started_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=launched_run_id,
                last_thread_id=launched_thread_id,
                last_error=None,
                increment_run_count=True,
                # Same race as the run-row write above: a fast-failing run's
                # completion hook may have already finalized a `once` task.
                protect_terminal=True,
            )
            return {
                "outcome": "launched",
                "task_run_id": task_run_id,
                "run_id": launched_run_id,
                "thread_id": launched_thread_id,
                "error": None,
            }
        except Exception as exc:
            if not launch_succeeded and self._is_overlap_conflict(exc):
                await self._task_run_repo.requeue_claimed_run(
                    task_run_id,
                    lease_owner=self._lease_owner,
                    error=str(exc),
                )
                return self._queued_result(task_run_id, execution_thread_id, error=str(exc))

            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )

            if launch_succeeded:
                # _launch_run succeeded, so a run is live even though
                # post-launch bookkeeping raised. Keep the task-run row
                # "running" so it keeps holding the task's single active slot
                # (preventing a duplicate launch on the next dispatch) and
                # persist the run_id on the parent task for recovery /
                # reconciliation / cancellation. These writes are best-effort:
                # if the DB is still down the row stays "queued" -- still
                # active, still holding the slot -- so we log and still report
                # the run as launched so callers know a run is in flight.
                task_status = self._task_status_for_launch(task, trigger=trigger)
                try:
                    await self._record_launched_run(
                        task_run_id=task_run_id,
                        task_id=task["id"],
                        run_id=launched_run_id,
                        started_at=now,
                    )
                except Exception:
                    logger.exception(
                        "Scheduled task-run %s: post-launch bookkeeping failed; run %s is still live (task %s)",
                        task_run_id,
                        launched_run_id,
                        task["id"],
                    )
                try:
                    await self._task_repo.update_after_launch(
                        task["id"],
                        status=task_status,
                        next_run_at=next_at,
                        last_run_at=now,
                        last_run_id=launched_run_id,
                        last_thread_id=launched_thread_id,
                        # The bookkeeping exception is an infrastructure-level
                        # transient, not a run-level failure: the run launched
                        # and is still in flight. Clear last_error like the
                        # success path so the task list does not show an error
                        # on a task whose run is actively running; the real
                        # terminal outcome is written by handle_run_completion.
                        # The transient itself is logged above.
                        last_error=None,
                        increment_run_count=True,
                        protect_terminal=True,
                    )
                except Exception:
                    logger.exception(
                        "Scheduled task %s: post-launch update failed; run %s is still live",
                        task["id"],
                        launched_run_id,
                    )
                return {
                    "outcome": "launched",
                    "task_run_id": task_run_id,
                    "run_id": launched_run_id,
                    "thread_id": launched_thread_id,
                    "error": str(exc),
                }

            # _launch_run itself failed (or a step before it did): no live run
            # was created, so it is safe to release the active slot.
            finalized = await self._task_run_repo.fail_launching_run(
                task_run_id,
                task_id=task["id"],
                lease_owner=self._lease_owner,
                error=str(exc),
                now=now,
            )
            if not finalized:
                logger.warning(
                    "Scheduled task-run %s lost its launch claim before failure bookkeeping; leaving recovery-owned state unchanged",
                    task_run_id,
                )
                return self._queued_result(task_run_id, execution_thread_id, error=str(exc))
            return {
                "outcome": "failed",
                "task_run_id": task_run_id,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": str(exc),
            }

    async def _record_launched_run(
        self,
        *,
        task_run_id: str,
        task_id: str,
        run_id: str,
        started_at: datetime,
    ) -> None:
        updated = await self._task_run_repo.update_status(
            task_run_id,
            status="running",
            run_id=run_id,
            started_at=started_at,
            protect_terminal=True,
            expected_lease_owner=self._lease_owner,
        )
        if updated:
            return
        reconciled = await self._task_run_repo.reconcile_launched_run(
            task_run_id,
            task_id=task_id,
            run_id=run_id,
            started_at=started_at,
        )
        if not reconciled:
            logger.error(
                "Scheduled task-run %s launched durable run %s but could not restore its occurrence association",
                task_run_id,
                run_id,
            )

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

    def _existing_active_result(
        self,
        active: dict[str, Any],
        thread_id: str,
        *,
        trigger: str,
    ) -> dict[str, Any]:
        if active["status"] == "queued":
            return self._queued_result(active["id"], active["thread_id"])
        return self._active_run_conflict_result(thread_id)

    @staticmethod
    def _queued_result(
        task_run_id: str,
        thread_id: str,
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "outcome": "queued",
            "task_run_id": task_run_id,
            "run_id": None,
            "thread_id": thread_id,
            "error": error,
        }

    async def _drain_queue(self, *, now: datetime) -> None:
        queued_rows = await self._task_run_repo.list_queued_runs(limit=max(16, self._max_concurrent_runs * 4))
        for queued in queued_rows:
            await self._task_repo.release_queued_admission_lease(queued["task_id"])
            task = await self._task_repo.get_internal(queued["task_id"])
            if task is None:
                await self._task_run_repo.update_status(
                    queued["id"],
                    status="interrupted",
                    error="scheduled task was deleted while queued",
                    finished_at=now,
                )
                continue
            # Pausing suppresses automatic occurrences, but a manual trigger is
            # an explicit request and has always been allowed to run without
            # resuming the schedule. A later pause still cancels an already
            # queued manual row atomically in pause_with_queue_cancellation().
            if task.get("status") == "paused" and queued["trigger"] != "manual":
                await self._task_run_repo.update_status(
                    queued["id"],
                    status="interrupted",
                    error="scheduled task was paused while queued",
                    finished_at=now,
                )
                continue
            await self._attempt_queued_run(task, queued, now=now)

    async def _expire_waiting_runs(self, *, now: datetime) -> None:
        await self._task_run_repo.expire_queued_runs(
            created_before=now - timedelta(seconds=self._queue_timeout_seconds),
            error=_QUEUE_TIMEOUT_ERROR,
            now=now,
        )

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
        restart_error = _RESTART_RECOVERY_ERROR
        if self._multi_instance:
            await self._reconcile_active_state(now=datetime.now(UTC))
            self._skip_next_lease_reconciliation = True
        else:
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

    async def _reconcile_active_state(self, *, now: datetime) -> None:
        error = _LEASE_RECOVERY_ERROR
        try:
            stale = await self._task_run_repo.reconcile_active_runs(
                error=error,
                now=now,
                lease_grace_seconds=self._run_lease_grace_seconds,
            )
            if stale:
                logger.warning("Marked %d stale scheduled task run(s) as interrupted after lease reconciliation", stale)
        except Exception:
            logger.exception("Failed to reconcile scheduled task runs with leases")
        try:
            stuck = await self._task_repo.reconcile_stuck_once_tasks(
                error=error,
                now=now,
                lease_grace_seconds=self._run_lease_grace_seconds,
            )
            if stuck:
                logger.warning("Cancelled %d stuck once task(s) after lease reconciliation", stuck)
        except Exception:
            logger.exception("Failed to reconcile once tasks with leases")

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
