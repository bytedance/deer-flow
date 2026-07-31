from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle of a standing instruction.

    RUNNING does not mean "the agent is executing" -- it means this dispatch
    round's scheduling ownership is held. That is why `ensure_mutable` refuses
    edits in that state, and why a crash can strand a task there.

    The last three are terminal for the *current* schedule, not forever: moving
    the schedule into the future re-arms them (see TERMINAL_TASK_STATUSES).
    """

    ENABLED = "enabled"
    PAUSED = "paused"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContextMode(StrEnum):
    """Which thread a dispatch executes in.

    REUSE_THREAD lets consecutive executions see each other's history and
    requires a thread up front; the default gives each one a fresh thread and
    therefore no shared context.
    """

    FRESH_THREAD_PER_RUN = "fresh_thread_per_run"
    REUSE_THREAD = "reuse_thread"


class ScheduleType(StrEnum):
    """How the next fire time is derived.

    The two branch almost every rule in this context: CRON always has a next
    occurrence, ONCE is consumed by its first one.
    """

    ONCE = "once"
    CRON = "cron"


class RunStatus(StrEnum):
    """Lifecycle of one execution record.

    QUEUED and RUNNING are the two that occupy a task's single active slot;
    everything else is terminal.

    SKIPPED is created directly terminal and never passes through QUEUED -- a
    queued tombstone would collide with the very run it is recording the
    overlap with (see ScheduledRun.skipped_tombstone). INTERRUPTED is kept
    distinct from FAILED because a cancel or takeover is not an execution
    failure, and the two lead a `once` task to different terminal states.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"


class DispatchOutcome(StrEnum):
    """What one dispatch attempt produced.

    A domain vocabulary rather than a set of strings: the caller branches on
    all four, and the distinction between SKIPPED and CONFLICT is itself a
    business rule -- a dropped scheduled occurrence is accounted for, while a
    rejected on-demand trigger is reported and leaves no trace.
    """

    LAUNCHED = "launched"
    SKIPPED = "skipped"
    CONFLICT = "conflict"
    FAILED = "failed"


class TriggerKind(StrEnum):
    """What caused a dispatch.

    The two kinds diverge in almost every decision the domain makes — how an
    overlap is handled, what status survives a failed launch, whether a paused
    task stays paused — so this is a first-class concept rather than the raw
    string the old service compared in four places.
    """

    SCHEDULED = "scheduled"
    MANUAL = "manual"
