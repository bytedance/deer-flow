"""Output ports of the schedule context.

Contracts the domain declares and the outer ring implements. Signatures are
technology-neutral: no SQL, table names, HTTP status codes, or run-runtime
types appear here, and every method exchanges domain objects.

The docstrings are longer than the code on purpose -- they are the semantic
contract the adapter must honour and the contract tests are written from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from deerflow.domain.schedule.model import (
    RunStatus,
    ScheduledRun,
    ScheduledTask,
    TaskStatus,
)


@dataclass(frozen=True)
class LaunchedRun:
    """What the launcher reports back once a run is admitted.

    `thread_id` is echoed rather than assumed: the launcher is free to return a
    different thread than the one requested, and the task's bookkeeping records
    what actually ran.
    """

    run_id: str
    thread_id: str


@dataclass(frozen=True)
class RunOutcome:
    """A launched run reaching a terminal state, in domain vocabulary.

    The app layer converts its own run record into this before calling the
    service, so the domain never imports the run runtime. That converter also
    owns the filtering the completion hook used to do inline -- a run that
    carries no scheduled-task metadata, or has not reached a terminal state,
    simply produces no RunOutcome and the service is never called.

    `status` is narrowed to the three terminal outcomes a scheduled run can
    report: SUCCESS, FAILED, INTERRUPTED. INTERRUPTED is deliberately distinct
    from FAILED -- a cancel or same-thread takeover is not an execution
    failure, and the task ends CANCELLED rather than FAILED.
    """

    task_id: str
    record_id: str
    run_id: str
    user_id: str
    status: RunStatus
    error: str | None


@runtime_checkable
class ScheduledTaskRepository(Protocol):
    """Persistence port for the task aggregate.

    Every read is scoped by `user_id`: a task belonging to someone else is
    reported as absent (None / False / omitted from a list), never as a
    permission error -- the caller must not be able to distinguish "not yours"
    from "does not exist".
    """

    async def add(self, task: ScheduledTask) -> ScheduledTask:
        """Insert a new task and return the stored state."""
        ...

    async def get(self, task_id: str, *, user_id: str) -> ScheduledTask | None:
        """Return the task, or None when it is absent or owned by someone else."""
        ...

    async def list_by_user(self, user_id: str) -> list[ScheduledTask]:
        """Every task owned by the user, newest first."""
        ...

    async def list_by_user_and_thread(self, user_id: str, thread_id: str) -> list[ScheduledTask]:
        """The user's tasks bound to one thread, newest first.

        Only `reuse_thread` tasks can match: a `fresh_thread_per_run` task
        carries no thread.
        """
        ...

    async def save(self, task: ScheduledTask) -> ScheduledTask | None:
        """Persist a whole aggregate, keyed by its own id and owner.

        Whole-aggregate replacement rather than a field patch: the aggregate is
        immutable, so a caller that changed anything is holding a complete new
        value. Returns None when the row is absent or owned by someone else.

        Not to be used for the post-dispatch write -- see `record_launch`.
        """
        ...

    async def delete(self, task_id: str, *, user_id: str) -> bool:
        """Remove the task. False when it was absent or owned by someone else."""
        ...

    async def claim_due(self, *, now: datetime, lease_seconds: int, limit: int) -> list[ScheduledTask]:
        """Atomically take ownership of up to `limit` tasks that are due.

        A task is due when its next fire time has passed AND either it is
        claimable (enabled, with no live claim), or it is stuck mid-dispatch
        with an expired claim -- the process that took it died between claiming
        and dispatching, and it must not stay unreachable forever.

        Claiming marks the tasks as running and stamps the claim, so a
        concurrent claimer cannot take the same ones. Returns them in the state
        they were left in *after* the claim.

        Which process is claiming is deliberately absent: it is an identity,
        not a rule. The implementation may record one for diagnostics, but
        nothing reads it back -- expiry alone decides whether a claim can be
        taken over -- so the domain has no reason to carry it.

        Atomicity is the implementation's responsibility. An in-memory double
        can satisfy every rule above under single-threaded use while providing
        no concurrency guarantee at all; that difference is out of scope for
        the contract tests and is covered separately against a real database.
        """
        ...

    async def record_launch(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        next_run_at: datetime | None,
        last_run_at: datetime | None,
        last_run_id: str | None,
        last_thread_id: str | None,
        last_error: str | None,
        increment_run_count: bool,
        protect_terminal: bool = False,
    ) -> None:
        """Write the outcome of a dispatch and release the claim.

        Deliberately NOT expressed as `save(task)`: `protect_terminal` makes
        this a compare-and-set against a run that may be finalizing
        concurrently. When it is set and the stored task has already reached a
        terminal status, the status and error are left alone and only the
        scheduling bookkeeping is written -- a read-modify-write through the
        aggregate would reintroduce the very race the flag exists to close.

        Every field is assigned unconditionally, so a caller preserving a value
        must pass the current one back. The claim is always released.
        """
        ...

    async def record_completion(
        self,
        task_id: str,
        *,
        user_id: str,
        status: TaskStatus | None,
        error: str | None,
    ) -> None:
        """Write a finished run's verdict onto the task.

        Deliberately NOT expressed as `save(task)`, for the same reason
        `record_launch` is not: the two race. A run that fails fast reaches its
        completion hook while the dispatch path is still writing its
        bookkeeping, so a read-modify-write through the aggregate would replay
        a snapshot taken before that write and roll it back -- restoring an
        elapsed `next_run_at` and an out-of-date `run_count`, and leaving the
        task in `running` with no live claim, which neither `claim_due` branch
        nor `cancel_stuck_once_tasks` can reach.

        The two writes therefore own disjoint fields: the launch owns the
        schedule, this owns the verdict. Nothing here touches `next_run_at`,
        `last_run_at`, `last_run_id`, `last_thread_id`, `run_count` or the
        claim.

        `status` is `None` when the verdict must not move the status -- every
        cron task, whose schedule outlives any single run. `error` is written
        either way, so a cron task still reports what went wrong last time.

        Scoped by `user_id` like every other read: a task belonging to someone
        else is left alone rather than reported. An unknown task is ignored --
        one deleted mid-flight simply has nothing to update.
        """
        ...

    async def cancel_stuck_once_tasks(self, *, error: str) -> int:
        """Reconcile `once` tasks orphaned mid-flight by a process crash.

        A launched `once` task waits in running for its completion hook, and
        its claim was released at launch -- so the expired-claim branch of
        `claim_due` can never see it, and after a crash the hook is gone. This
        marks those tasks cancelled and returns how many were reconciled.

        Tasks still holding a claim are left alone: they were claimed but not
        launched, and expired-claim reclaim recovers them safely.
        """
        ...


@runtime_checkable
class ScheduledRunRepository(Protocol):
    """Persistence port for execution records.

    Unlike tasks, runs are not read by owner: they are only ever reached
    through a task the caller already proved it owns.
    """

    async def add(self, run: ScheduledRun) -> ScheduledRun:
        """Insert an execution record.

        Raises:
            ActiveRunConflictError: the task already holds its single active
                slot. Translating the storage-level rejection into this domain
                error is the adapter's job and is load-bearing -- the service
                collapses it to exactly the same outcome as the `has_active`
                fast path, and those two paths must stay indistinguishable.

        A terminal record (a skip tombstone) is outside the active-slot rule
        and must never raise it.
        """
        ...

    async def list_by_task(self, task_id: str, *, limit: int, offset: int) -> list[ScheduledRun]:
        """One task's execution history, newest first."""
        ...

    async def count_active(self) -> int:
        """How many executions are active across ALL tasks.

        Global on purpose: it bounds total scheduled concurrency, not per-task
        overlap. Long runs accumulate across polls, so each poll may only claim
        into whatever budget is left.
        """
        ...

    async def has_active(self, task_id: str) -> bool:
        """Whether this task currently holds its active slot.

        A non-atomic fast path by nature -- it cannot be relied on to exclude a
        concurrent dispatch. `add` is the arbiter; this exists to avoid the
        common case of doing pointless work.
        """
        ...

    async def update_status(
        self,
        record_id: str,
        *,
        status: RunStatus,
        run_id: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        protect_terminal: bool = False,
    ) -> None:
        """Advance an execution record.

        With `protect_terminal`, a record that already reached a terminal state
        keeps its status and error; only bookkeeping the terminal write could
        not have known (the run id, the start time) is backfilled. A run that
        fails fast can reach its completion hook before the launch path's own
        write lands, and the completion is the authoritative one.

        Unknown record ids are ignored rather than raising: the caller is
        writing bookkeeping, not asserting existence.
        """
        ...

    async def mark_stale_active(self, *, error: str) -> int:
        """Terminalize executions orphaned by a process crash, returning the count.

        Runs execute in-process, so any record still active at startup belongs
        to a process that is gone. This is only sound while a single scheduler
        instance owns the table.
        """
        ...


class RunLauncher(Protocol):
    """Output port for actually starting the work.

    The contract the adapter MUST honour, because it is what keeps the run
    runtime and the web framework out of the inner ring:

      - the execution thread is already busy  -> ThreadBusyError
      - anything else goes wrong              -> LaunchFailedError

    Nothing else may escape. The domain distinguishes those two because they
    lead to different outcomes -- a busy thread on a scheduled dispatch is a
    skipped occurrence, while a genuine failure is recorded as one.
    """

    async def launch(
        self,
        *,
        thread_id: str,
        assistant_id: str | None,
        prompt: str,
        owner_user_id: str | None,
        metadata: dict[str, str],
    ) -> LaunchedRun:
        """Start one execution and return its identity.

        `metadata` is opaque correlation data the domain attaches so the
        eventual outcome can be traced back to this task and record; the
        adapter must carry it through untouched.
        """
        ...


class ThreadLookup(Protocol):
    """Narrow port: the only question the schedule context asks about threads.

    Deliberately not the full thread store -- depending on this one method
    keeps the context decoupled from the wider conversation model.
    """

    async def exists_for_user(self, thread_id: str, user_id: str) -> bool:
        """Whether this thread exists AND the user may use it.

        Both halves matter: binding a task to a thread that does not exist yet
        is as invalid as binding it to someone else's. The two are deliberately
        not distinguished in the result -- reporting them differently would let
        a caller probe for the existence of threads they cannot see.
        """
        ...
