"""Application service of the schedule context (its input port).

Orchestrates use cases only: fetch, apply domain rules, persist through output
ports. It holds no business rules itself -- every decision below is delegated
to the aggregate -- and knows nothing about HTTP, SQL, or the run runtime.
`user_id` is always passed in explicitly; resolving the current user is the
primary adapter's job.

The dispatch path deliberately mirrors the structure of the legacy
`app/scheduler/service.py` (still present until the adapter slice replaces
it), including its ordering, its comments, and its post-launch retention
semantics (#4452 / #4504), because its concurrency and idempotency semantics
are load-bearing and are pinned by tests that must keep passing unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime

from deerflow.domain.schedule.commands import (
    UNSET,
    CreateScheduledTask,
    DeleteTask,
    PauseTask,
    ResumeTask,
    TriggerTask,
    UpdateScheduledTask,
)
from deerflow.domain.schedule.exceptions import (
    ActiveRunConflictError,
    LaunchFailedError,
    LaunchIndeterminateError,
    TaskNotFoundError,
    ThreadBusyError,
    ThreadNotFoundError,
)
from deerflow.domain.schedule.model import (
    ContextMode,
    DispatchOutcome,
    RunStatus,
    ScheduledRun,
    ScheduledTask,
    SchedulePolicy,
    ScheduleType,
    TriggerKind,
)
from deerflow.domain.schedule.ports import (
    RunLauncher,
    RunOutcome,
    ScheduledRunRepository,
    ScheduledTaskRepository,
    ThreadLookup,
)

logger = logging.getLogger(__name__)

# Shared so the has_active fast path and the active-slot race path produce
# byte-identical outcomes for the same "task already has an active run"
# condition. Two callers must not be able to tell which one rejected them.
_ACTIVE_RUN_CONFLICT_ERROR = "task already has an active run"
_SKIP_ACTIVE_RUN_ERROR = "skipped: a previous run of this task is still active"


@dataclass(frozen=True)
class DispatchResult:
    """What one dispatch attempt produced.

    `outcome` drives the caller's protocol mapping -- a manual trigger turns
    CONFLICT into 409 and FAILED into 502 -- so it is domain vocabulary
    rather than a bare string.
    """

    outcome: DispatchOutcome
    record_id: str | None
    run_id: str | None
    thread_id: str
    error: str | None


class ScheduleService:
    """Every scheduled-task use case, orchestrated over the four output ports.

    The input port of this context: primary adapters (an HTTP router, the
    poller, the run-completion hook) call these methods and translate what
    comes back. Domain errors are allowed to propagate -- mapping them onto a
    protocol is the adapter's job, not this class's.
    """

    def __init__(
        self,
        *,
        tasks: ScheduledTaskRepository,
        runs: ScheduledRunRepository,
        launcher: RunLauncher,
        threads: ThreadLookup,
        policy: SchedulePolicy,
    ) -> None:
        self._tasks = tasks
        self._runs = runs
        self._launcher = launcher
        self._threads = threads
        self._policy = policy

    # ------------------------------------------------------------------ reads

    async def list_tasks(self, user_id: str) -> list[ScheduledTask]:
        """Every task the user owns, newest first."""
        return await self._tasks.list_by_user(user_id)

    async def list_tasks_by_thread(self, user_id: str, thread_id: str) -> list[ScheduledTask]:
        """The user's tasks bound to one thread.

        Only reuse_thread tasks can appear: a fresh-thread task carries no
        binding to show.
        """
        return await self._tasks.list_by_user_and_thread(user_id, thread_id)

    async def get_task(self, task_id: str, *, user_id: str) -> ScheduledTask:
        """Raises TaskNotFoundError when absent or owned by someone else -- the
        caller must not be able to tell those apart."""
        task = await self._tasks.get(task_id, user_id=user_id)
        if task is None:
            raise TaskNotFoundError("Scheduled task not found")
        return task

    async def list_task_runs(self, task_id: str, *, user_id: str, limit: int = 50, offset: int = 0) -> list[ScheduledRun]:
        """Execution history, gated on ownership of the parent task."""
        await self.get_task(task_id, user_id=user_id)
        return await self._runs.list_by_task(task_id, limit=limit, offset=offset)

    # ------------------------------------------------------------------ writes

    async def create_scheduled_task(self, cmd: CreateScheduledTask, *, now: datetime) -> ScheduledTask:
        """Register a new standing instruction.

        The aggregate is built first so a malformed schedule or context mode is
        reported as such before any IO happens; only then is the thread
        binding verified.

        Raises:
            InvalidScheduleError / InvalidContextModeError: from the aggregate.
            ThreadNotFoundError: reuse_thread pointing at a thread the user
                cannot use.
        """
        task = ScheduledTask.create(
            user_id=cmd.user_id,
            title=cmd.title,
            prompt=cmd.prompt,
            schedule=cmd.schedule,
            context_mode=cmd.context_mode,
            thread_id=cmd.thread_id,
            now=now,
            policy=self._policy,
        )
        await self._require_thread(task)
        return await self._tasks.add(task)

    async def update_scheduled_task(self, cmd: UpdateScheduledTask, *, now: datetime) -> ScheduledTask:
        """Partially update a task; ``UNSET`` means "not supplied".

        The one field for which ``None`` is a meaningful value, `thread_id`,
        travels inside `ContextChange` where it is unambiguous.

        Context and schedule are applied through the aggregate's own
        transitions, so the re-arm rule and the running-task gate cannot be
        bypassed by patching fields directly.
        """
        task = await self.get_task(cmd.task_id, user_id=cmd.user_id)
        task.ensure_mutable()

        if cmd.context is not UNSET:
            task = task.with_context(cmd.context.context_mode, cmd.context.thread_id)
            await self._require_thread(task)
        if cmd.schedule is not UNSET:
            task = task.with_schedule(cmd.schedule, now=now, policy=self._policy)
        if cmd.title is not UNSET:
            task = replace(task, title=cmd.title)
        if cmd.prompt is not UNSET:
            task = replace(task, prompt=cmd.prompt)

        return await self._save(task)

    async def pause_task(self, cmd: PauseTask) -> ScheduledTask:
        """Stop claiming this task until it is resumed.

        Refused while the task is being dispatched -- see `ensure_mutable`.
        """
        task = await self.get_task(cmd.task_id, user_id=cmd.user_id)
        return await self._save(task.paused())

    async def resume_task(self, cmd: ResumeTask) -> ScheduledTask:
        """Re-admit this task to claiming. Same gate as `pause_task`."""
        task = await self.get_task(cmd.task_id, user_id=cmd.user_id)
        return await self._save(task.resumed())

    async def delete_task(self, cmd: DeleteTask) -> None:
        """Deleting is deliberately not gated on the task being idle: the
        pre-migration router applied that gate to update/pause/resume only."""
        if not await self._tasks.delete(cmd.task_id, user_id=cmd.user_id):
            raise TaskNotFoundError("Scheduled task not found")

    # ------------------------------------------------------------------ dispatch

    async def trigger_task(self, cmd: TriggerTask, *, now: datetime) -> DispatchResult:
        """Dispatch a task on demand. Unlike the scheduled path this is allowed
        while the task is paused, and leaves it paused."""
        task = await self.get_task(cmd.task_id, user_id=cmd.user_id)
        return await self.dispatch_task(task, now=now, trigger=TriggerKind.MANUAL)

    async def run_once(self, *, now: datetime) -> list[DispatchResult]:
        """Claim whatever is due and dispatch it.

        `max_concurrent_runs` is a global cap on active scheduled runs, not a
        per-poll batch size: long runs accumulate across poll cycles, so each
        cycle only claims into the remaining budget.
        """
        active = await self._runs.count_active()
        budget = self._policy.max_concurrent_runs - active
        if budget <= 0:
            return []
        claimed = await self._tasks.claim_due(now=now, lease_seconds=self._policy.lease_seconds, limit=budget)
        return [await self.dispatch_task(task, now=now, trigger=TriggerKind.SCHEDULED) for task in claimed]

    async def dispatch_task(self, task: ScheduledTask, *, now: datetime, trigger: TriggerKind) -> DispatchResult:
        """Turn one due task into one execution.

        Called once per dispatch, so `resolve_execution_thread` is called once
        and its value reused for the record, the launch, and the result.
        """
        execution_thread_id = task.resolve_execution_thread()

        # "skip" must hold for fresh-thread runs too, where every run gets a
        # new thread and the same-thread busy signal below can never fire.
        # Checked before creating this dispatch's own record so the record does
        # not count itself as the active run. A manual trigger against an
        # active run is rejected outright instead of being recorded as a
        # skipped occurrence -- nothing was scheduled to happen.
        #
        # This check is a NON-ATOMIC fast path: two concurrent dispatches (a
        # manual trigger racing the poller, a double-click, a client retry) can
        # both observe no active run. The repository is the atomic arbiter --
        # it rejects the second active record with ActiveRunConflictError,
        # which collapses to the SAME outcome as this fast path just below.
        if task.skips_on_overlap and await self._runs.has_active(task.task_id):
            if trigger is TriggerKind.MANUAL:
                return self._conflict(execution_thread_id)
            return await self._record_scheduled_skip(task, thread_id=execution_thread_id, now=now, trigger=trigger)

        record = ScheduledRun.queued(
            task_id=task.task_id,
            thread_id=execution_thread_id,
            scheduled_for=now,
            trigger=trigger,
        )
        try:
            await self._runs.add(record)
        except ActiveRunConflictError:
            # Lost the race for the task's single active slot: a concurrent
            # dispatch passed the same fast-path check and inserted first.
            # Identical outcome to the fast path above -- that equality is what
            # the dispatch-race regression tests pin.
            if trigger is TriggerKind.MANUAL:
                return self._conflict(execution_thread_id)
            return await self._record_scheduled_skip(task, thread_id=execution_thread_id, now=now, trigger=trigger)

        # Only the launch is guarded, and only its two certain outcomes may
        # release the slot. Past this point a live run may exist, so every
        # failure -- an indeterminate launch, a bookkeeping write dying -- must
        # take the retention path below rather than mark the record failed:
        # "failed" is terminal, terminal records do not hold the task's single
        # active slot, and a released slot lets the next dispatch launch a
        # duplicate of a run that is still alive (#4452, fixed by #4504).
        try:
            launched = await self._launcher.launch(
                thread_id=execution_thread_id,
                assistant_id=task.assistant_id,
                prompt=task.prompt,
                owner_user_id=task.user_id,
                metadata={
                    "scheduled_task_id": task.task_id,
                    "scheduled_task_run_id": record.record_id,
                    "scheduled_trigger": str(trigger),
                },
            )
        except ThreadBusyError as exc:
            # The execution thread is already busy. On the scheduled path under
            # a skip policy this is an overlap like any other; anything else is
            # reported as a conflict the caller has to deal with.
            if trigger is TriggerKind.SCHEDULED and task.skips_on_overlap:
                return await self._finalize_skip(task, record_id=record.record_id, thread_id=execution_thread_id, now=now, error=str(exc))
            return await self._fail(task, record_id=record.record_id, thread_id=execution_thread_id, now=now, trigger=trigger, error=str(exc), outcome=DispatchOutcome.CONFLICT)
        except LaunchFailedError as exc:
            # The adapter certifies no run started (see the port contract), so
            # releasing the slot is safe.
            return await self._fail(task, record_id=record.record_id, thread_id=execution_thread_id, now=now, trigger=trigger, error=str(exc), outcome=DispatchOutcome.FAILED)
        except LaunchIndeterminateError as exc:
            # The launch side effect may have happened but its identity could
            # not be decoded. Retain the slot with the identity unknown;
            # reconciliation settles what actually happened.
            return await self._retain_launched(task, record_id=record.record_id, run_id=None, thread_id=execution_thread_id, now=now, trigger=trigger, error=str(exc))

        return await self._retain_launched(task, record_id=record.record_id, run_id=launched.run_id, thread_id=launched.thread_id, now=now, trigger=trigger, error=None)

    # ------------------------------------------------------------------ lifecycle

    async def handle_run_completion(self, outcome: RunOutcome, *, now: datetime) -> None:
        """Write back a launched run's terminal verdict.

        A task deleted while its run was in flight simply has nothing to
        update, and that is not an error.
        """
        await self._runs.update_status(
            outcome.record_id,
            status=outcome.status,
            run_id=outcome.run_id,
            error=outcome.error,
            finished_at=now,
        )
        # Read to ask the aggregate what this outcome means, then write only
        # that. `status_after_completion` reads nothing but the schedule type,
        # which no concurrent write can change, so this read carries no
        # time-of-check risk -- and `record_completion` deliberately does not
        # write the fields that a concurrent `record_launch` owns.
        task = await self._tasks.get(outcome.task_id, user_id=outcome.user_id)
        if task is None:
            return
        # The error is recorded whether or not the status moves: a cron task
        # keeps its schedule but still reports what went wrong last time.
        await self._tasks.record_completion(
            outcome.task_id,
            user_id=outcome.user_id,
            status=task.status_after_completion(outcome.status),
            error=outcome.error,
        )

    async def reconcile_on_startup(self, *, error: str) -> tuple[int, int]:
        """Clean up what a process crash left behind, returning what was fixed.

        Two sweeps, because a crash strands two different things: execution
        records that can never finish, and `once` tasks parked waiting for a
        completion hook that died with the process. The second is not covered
        by expired-claim reclaim -- a launched task released its claim, so the
        claim query can never see it again.

        Failures propagate: whether a partial reconcile should block startup is
        the caller's policy, not the domain's.
        """
        stale_runs = await self._runs.mark_stale_active(error=error)
        stuck_tasks = await self._tasks.cancel_stuck_once_tasks(error=error)
        return stale_runs, stuck_tasks

    # ------------------------------------------------------------------ internals

    async def _require_thread(self, task: ScheduledTask) -> None:
        if task.context_mode is not ContextMode.REUSE_THREAD:
            return
        # The aggregate guarantees a thread here; the check keeps that
        # guarantee from being silently dropped under `python -O`.
        if not task.thread_id or not await self._threads.exists_for_user(task.thread_id, task.user_id):
            raise ThreadNotFoundError("Thread not found")

    async def _save(self, task: ScheduledTask) -> ScheduledTask:
        """Persist an already-validated aggregate.

        Read-modify-write rather than a conditional UPDATE: pushing the
        "not while running" rule into a storage predicate would put it beyond
        the reach of a zero-IO test and give it a second home. The pre-existing
        code had the same shape, and closing the window properly needs
        optimistic locking, which needs a schema change.
        """
        saved = await self._tasks.save(task)
        if saved is None:
            raise TaskNotFoundError("Scheduled task not found")
        return saved

    async def _retain_launched(
        self,
        task: ScheduledTask,
        *,
        record_id: str,
        run_id: str | None,
        thread_id: str,
        now: datetime,
        trigger: TriggerKind,
        error: str | None,
    ) -> DispatchResult:
        """Record a launch whose run is (or may be) live. Best-effort by design.

        Both writes are attempted independently and their failures logged
        rather than raised: the run is already in flight, so there is no
        outcome these writes could change -- only bookkeeping they could lose.
        A failed record write leaves the row queued, a failed task write
        leaves the claim held; both states still hold the task's single
        active slot, which is the invariant that matters (#4452). The first
        error is surfaced on the result so the caller knows the bookkeeping
        is behind, while the outcome stays LAUNCHED.
        """
        try:
            await self._runs.update_status(
                record_id,
                status=RunStatus.RUNNING,
                run_id=run_id,
                started_at=now,
                # A fast-failing run can reach handle_run_completion before
                # this write lands; never clobber its terminal verdict.
                protect_terminal=True,
            )
        except Exception:
            logger.exception("Scheduled run record %s: post-launch bookkeeping failed; run %s is still live (task %s)", record_id, run_id, task.task_id)
            if error is None:
                error = f"post-launch bookkeeping failed for record {record_id}"
        try:
            await self._tasks.record_launch(
                task.task_id,
                status=task.status_after_launch(trigger=trigger),
                next_run_at=task.schedule.next_after(now),
                last_run_at=now,
                last_run_id=run_id,
                last_thread_id=thread_id,
                # A bookkeeping transient is not the run's verdict: the launch
                # succeeded, so the task list must not show an error while the
                # run is in flight. handle_run_completion writes the real one.
                last_error=None,
                increment_run_count=True,
                # Same race as the record write above.
                protect_terminal=True,
            )
        except Exception:
            logger.exception("Scheduled task %s: post-launch update failed; run %s is still live", task.task_id, run_id)
            if error is None:
                error = f"post-launch bookkeeping failed for task {task.task_id}"
        return DispatchResult(DispatchOutcome.LAUNCHED, record_id, run_id, thread_id, error)

    def _conflict(self, thread_id: str) -> DispatchResult:
        """A manual trigger against an active run.

        No history record is written: nothing was scheduled to happen, so there
        is no occurrence to account for.
        """
        return DispatchResult(DispatchOutcome.CONFLICT, None, None, thread_id, _ACTIVE_RUN_CONFLICT_ERROR)

    async def _record_scheduled_skip(self, task: ScheduledTask, *, thread_id: str, now: datetime, trigger: TriggerKind) -> DispatchResult:
        """Account for a scheduled occurrence dropped because of an overlap.

        The tombstone is created directly terminal rather than as the transient
        queued record the launch path uses: a queued record is active and would
        itself be refused against the pre-existing run that is still holding
        the task's single active slot.
        """
        record = ScheduledRun.skipped_tombstone(
            task_id=task.task_id,
            thread_id=thread_id,
            scheduled_for=now,
            trigger=trigger,
        )
        await self._runs.add(record)
        return await self._finalize_skip(task, record_id=record.record_id, thread_id=thread_id, now=now, error=_SKIP_ACTIVE_RUN_ERROR)

    async def _finalize_skip(self, task: ScheduledTask, *, record_id: str, thread_id: str, now: datetime, error: str) -> DispatchResult:
        await self._runs.update_status(
            record_id,
            status=RunStatus.SKIPPED,
            error=error,
            started_at=now,
            finished_at=now,
        )
        await self._tasks.record_launch(
            task.task_id,
            status=task.status_after_skip(),
            next_run_at=task.schedule.next_after(now),
            # A skip is not an execution, so the launch bookkeeping carries
            # over unchanged; record_launch assigns unconditionally, so
            # "unchanged" has to be spelled out.
            last_run_at=task.last_run_at,
            last_run_id=task.last_run_id,
            last_thread_id=task.last_thread_id,
            # Only a lost one-shot occurrence is worth surfacing; a cron task
            # simply waits for its next turn.
            last_error=error if task.schedule.schedule_type is ScheduleType.ONCE else None,
            increment_run_count=False,
        )
        return DispatchResult(DispatchOutcome.SKIPPED, record_id, None, thread_id, error)

    async def _fail(
        self,
        task: ScheduledTask,
        *,
        record_id: str,
        thread_id: str,
        now: datetime,
        trigger: TriggerKind,
        error: str,
        outcome: DispatchOutcome,
    ) -> DispatchResult:
        await self._runs.update_status(
            record_id,
            status=RunStatus.FAILED,
            error=error,
            started_at=now,
            finished_at=now,
        )
        await self._tasks.record_launch(
            task.task_id,
            status=task.status_after_failure(trigger=trigger),
            next_run_at=task.schedule.next_after(now),
            last_run_at=now,
            last_run_id=None,
            last_thread_id=thread_id,
            last_error=error,
            increment_run_count=False,
        )
        return DispatchResult(outcome, record_id, None, thread_id, error)
