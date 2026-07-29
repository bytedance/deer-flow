from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from deerflow.domain.schedule.exceptions import InvalidContextModeError, TaskNotMutableError
from deerflow.domain.schedule.model.enums import ContextMode, RunStatus, ScheduleType, TaskStatus, TriggerKind
from deerflow.domain.schedule.model.spec import SchedulePolicy, ScheduleSpec

TERMINAL_TASK_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})
"""The statuses in which a task's current schedule is done.

Lives here rather than in enums.py: it is a business subset of TaskStatus, so
it belongs beside the aggregate that reasons about it.

Two rules read it, and they share one constant rather than drifting into two
same-valued ones:

- `with_schedule` re-arms them to ENABLED once the schedule moves into the
  future — claiming only admits ENABLED rows, so leaving a terminal status
  there would hand back a next_run_at that silently never fires.
- The repository's `protect_terminal` compare-and-set refuses to overwrite
  them, because a fast-failing run's completion hook can land before the launch
  path's own write (scheduled_tasks/sql.py:12).

The two coincide because terminal *is* the definition of re-armable. The name
states what the statuses are; what each rule does with them belongs to that
rule.
"""


def _parse_context_mode(value: str | ContextMode) -> ContextMode:
    """Coerce a wire-level context_mode into the enum.

    Reported as InvalidContextModeError rather than letting ValueError
    escape, so the router can map the whole ScheduleError family uniformly
    — an unknown mode was a 422 at router:76-77.
    """
    try:
        return ContextMode(value)
    except ValueError as exc:
        raise InvalidContextModeError(f"Unsupported context_mode: {value}") from exc


@dataclass(frozen=True)
class ScheduledTask:
    """A user's standing instruction to run one prompt on a schedule.

    Aggregate root of the schedule context. Holds every invariant the old
    router/service pair scattered across three files; nothing here knows about
    HTTP, SQL, or the run runtime.

    The `with_*` / `paused` / `resumed` transitions return a new aggregate and
    deliberately leave `updated_at` alone: the repository stamps it on write
    (scheduled_tasks/sql.py:97), and a second clock read here would make the
    domain both impure and a competing source of truth for the same column.
    """

    task_id: str
    user_id: str
    title: str
    prompt: str
    schedule: ScheduleSpec
    context_mode: ContextMode = ContextMode.FRESH_THREAD_PER_RUN
    thread_id: str | None = None
    assistant_id: str | None = "lead_agent"
    status: TaskStatus = TaskStatus.ENABLED
    # The MVP fixes this to "skip"; a single-valued enum would be noise. The
    # comparison is confined to `skips_on_overlap` so a second policy only has
    # to change one place.
    overlap_policy: str = "skip"
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_id: str | None = None
    last_thread_id: str | None = None
    last_error: str | None = None
    run_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.context_mode is ContextMode.REUSE_THREAD and not self.thread_id:
            raise InvalidContextModeError("reuse_thread requires thread_id")

    @classmethod
    def create(
        cls,
        *,
        user_id: str,
        title: str,
        prompt: str,
        schedule: ScheduleSpec,
        context_mode: str | ContextMode,
        thread_id: str | None,
        now: datetime,
        policy: SchedulePolicy,
    ) -> ScheduledTask:
        """Factory: generate identity, normalize context, validate invariants.

        FRESH_THREAD_PER_RUN drops any supplied thread_id (router:164-165 does
        the same on update) — carrying a thread the task will never use would
        make `resolve_execution_thread` ambiguous.

        Thread existence/ownership is NOT checked here: that needs the
        ThreadLookup port and belongs to the service.
        """
        mode = _parse_context_mode(context_mode)
        effective_thread = thread_id if mode is ContextMode.REUSE_THREAD else None
        return cls(
            task_id=f"task-{uuid.uuid4().hex}",
            user_id=user_id,
            title=title,
            prompt=prompt,
            schedule=schedule,
            context_mode=mode,
            thread_id=effective_thread,
            next_run_at=schedule.ensure_launchable(now, policy),
        )

    @property
    def skips_on_overlap(self) -> bool:
        """Whether an overlapping dispatch is dropped rather than queued."""
        return self.overlap_policy == "skip"

    def resolve_execution_thread(self) -> str:
        """Pick the thread this dispatch executes in (service.py:94-96).

        NOT idempotent: FRESH_THREAD_PER_RUN mints a new uuid4 on every call,
        so a dispatch must call this exactly once and reuse the value for the
        run row, the launch, and the result.

        The empty-thread_id fallback is kept even though __post_init__ makes it
        unreachable for new aggregates — rows predating that invariant can
        still carry REUSE_THREAD with no thread.
        """
        if self.context_mode is ContextMode.FRESH_THREAD_PER_RUN or not self.thread_id:
            return str(uuid.uuid4())
        return self.thread_id

    def ensure_mutable(self) -> None:
        """Reject edits while this dispatch round's lease is held.

        Was `_ensure_task_mutable` in the router (409). Called by every
        state-changing method here rather than by the caller, so the rule
        cannot be forgotten at a new call site. The router historically applied
        it to update/pause/resume but not trigger/delete; that asymmetry is
        intentional and is preserved by keeping those two off this path.

        Raises:
            TaskNotMutableError: the task is currently RUNNING.
        """
        if self.status is TaskStatus.RUNNING:
            raise TaskNotMutableError("Scheduled task is currently running; retry after the active execution finishes")

    def status_after_launch(self, *, trigger: TriggerKind) -> TaskStatus:
        """Status to persist after a successful launch (service.py:152-161).

        Precondition on `self.status`: for a SCHEDULED trigger it is already
        RUNNING (written by claim_due); for a MANUAL trigger it is the
        user-facing status. The PAUSED rule below depends on that.

        Decision order is load-bearing — ONCE is tested first, so manually
        triggering a paused ONCE task yields RUNNING, not PAUSED:

            ONCE                          -> RUNNING (await the completion
                                             hook; declaring COMPLETED at
                                             launch would stick if the run
                                             fails or the process dies)
            MANUAL and self.status PAUSED -> PAUSED  (a manual run must not
                                             silently resume the schedule)
            otherwise                     -> ENABLED
        """
        if self.schedule.schedule_type is ScheduleType.ONCE:
            return TaskStatus.RUNNING
        if trigger is TriggerKind.MANUAL and self.status is TaskStatus.PAUSED:
            return TaskStatus.PAUSED
        return TaskStatus.ENABLED

    def status_after_failure(self, *, trigger: TriggerKind) -> TaskStatus:
        """Status to persist after a failed launch (was _task_status_for_failure).

        Decision order is load-bearing — MANUAL is tested first, so a failed
        manual trigger of a ONCE task keeps its status instead of burning the
        occurrence:

            MANUAL          -> self.status (unchanged; the old dict-based code
                               needed an `or "enabled"` fallback, which the
                               field default makes unnecessary here)
            SCHEDULED, ONCE -> FAILED
            SCHEDULED, CRON -> ENABLED (the next occurrence still stands)
        """
        if trigger is TriggerKind.MANUAL:
            return self.status
        if self.schedule.schedule_type is ScheduleType.ONCE:
            return TaskStatus.FAILED
        return TaskStatus.ENABLED

    def status_after_skip(self) -> TaskStatus:
        """Status to persist after an overlap skip (was _task_status_for_skip).

        No `trigger` parameter: a skip only happens on the SCHEDULED path — a
        manual trigger that overlaps is rejected outright and records no run
        row at all, so a parameter here would imply a branch that cannot exist.

            ONCE -> FAILED   (the single occurrence was lost; COMPLETED would
                              claim an execution that never happened)
            CRON -> ENABLED
        """
        if self.schedule.schedule_type is ScheduleType.ONCE:
            return TaskStatus.FAILED
        return TaskStatus.ENABLED

    def status_after_completion(self, outcome: RunStatus) -> TaskStatus | None:
        """Status to persist when a launched run reaches a terminal state.

        Returns None when the status must not change — every CRON task, whose
        schedule outlives any single run.

            CRON              -> None
            ONCE, SUCCESS     -> COMPLETED
            ONCE, INTERRUPTED -> CANCELLED (a cancel or same-thread takeover is
                                 not an execution failure)
            ONCE, otherwise   -> FAILED

        The occurrence is consumed either way: the run did launch, so re-arming
        would risk duplicate side effects. Note the caller writes `last_error`
        unconditionally, whether or not this returns None (service.py:346).
        """
        if self.schedule.schedule_type is not ScheduleType.ONCE:
            return None
        if outcome is RunStatus.SUCCESS:
            return TaskStatus.COMPLETED
        if outcome is RunStatus.INTERRUPTED:
            return TaskStatus.CANCELLED
        return TaskStatus.FAILED

    def with_schedule(self, schedule: ScheduleSpec, *, now: datetime, policy: SchedulePolicy) -> ScheduledTask:
        """Replace the schedule and recompute next_run_at (router:172-208).

        A terminal task whose schedule just moved into the future must be
        re-armed: claim_due only admits ENABLED rows, so leaving the terminal
        status would return 200 with a next_run_at that silently never fires.

        Raises:
            TaskNotMutableError: via ensure_mutable.
            InvalidScheduleError: via ensure_launchable.
        """
        self.ensure_mutable()
        next_at = schedule.ensure_launchable(now, policy)
        status = TaskStatus.ENABLED if next_at is not None and self.status in TERMINAL_TASK_STATUSES else self.status
        return replace(self, schedule=schedule, next_run_at=next_at, status=status)

    def with_context(self, context_mode: str | ContextMode, thread_id: str | None) -> ScheduledTask:
        """Replace execution context (router:153-165).

        FRESH_THREAD_PER_RUN forces thread_id to None. Thread existence is the
        service's job (ThreadLookup port), not this aggregate's.

        Raises:
            TaskNotMutableError: via ensure_mutable.
            InvalidContextModeError: unknown mode, or REUSE_THREAD with no
                thread (raised by __post_init__ on the replacement).
        """
        self.ensure_mutable()
        mode = _parse_context_mode(context_mode)
        effective_thread = thread_id if mode is ContextMode.REUSE_THREAD else None
        return replace(self, context_mode=mode, thread_id=effective_thread)

    def paused(self) -> ScheduledTask:
        """Stop claiming this task until resumed."""
        self.ensure_mutable()
        return replace(self, status=TaskStatus.PAUSED)

    def resumed(self) -> ScheduledTask:
        """Re-admit this task to claim_due."""
        self.ensure_mutable()
        return replace(self, status=TaskStatus.ENABLED)
