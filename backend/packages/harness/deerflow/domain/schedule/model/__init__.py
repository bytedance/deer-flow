"""Domain model of the schedule context.

A package rather than a single module because this context has two
aggregates plus a value object (Feedback, the first slice, needed only
92 lines and stayed a module). Re-exports below make the split
invisible to callers: `deerflow.domain.schedule.model` exposes exactly
what a single `model.py` would have.

The re-exports below are ordered alphabetically because ruff's isort rule
owns that block; alphabetical happens to satisfy the real dependency order
too (enums and errors depend on nothing, run depends on enums, spec depends
on enums and errors, task depends on all three), so it needs no override.

What actually keeps the package acyclic is a rule isort cannot express:
**a submodule imports its siblings directly, never this package.** Reaching
back through `deerflow.domain.schedule.model` makes a submodule depend on a
partially initialized package — it only works while the symbol happens to
sit above that submodule's own line here, and reordering this block silently
breaks it. Keep it that way.
"""

from deerflow.domain.schedule.model.enums import (
    ContextMode,
    DispatchOutcome,
    RunStatus,
    ScheduleType,
    TaskStatus,
    TriggerKind,
)
from deerflow.domain.schedule.model.errors import (
    ActiveRunConflictError,
    InvalidContextModeError,
    InvalidScheduleError,
    LaunchFailedError,
    ScheduleError,
    TaskNotFoundError,
    TaskNotMutableError,
    ThreadBusyError,
    ThreadNotFoundError,
)
from deerflow.domain.schedule.model.run import ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, ScheduledRun
from deerflow.domain.schedule.model.spec import CRON_FIELD_COUNT, SchedulePolicy, ScheduleSpec
from deerflow.domain.schedule.model.task import TERMINAL_TASK_STATUSES, ScheduledTask

__all__ = [
    "ACTIVE_RUN_STATUSES",
    "CRON_FIELD_COUNT",
    "TERMINAL_RUN_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "ActiveRunConflictError",
    "ContextMode",
    "DispatchOutcome",
    "InvalidContextModeError",
    "InvalidScheduleError",
    "LaunchFailedError",
    "RunStatus",
    "ScheduleError",
    "SchedulePolicy",
    "ScheduleSpec",
    "ScheduleType",
    "ScheduledRun",
    "ScheduledTask",
    "TaskNotFoundError",
    "TaskNotMutableError",
    "TaskStatus",
    "ThreadBusyError",
    "ThreadNotFoundError",
    "TriggerKind",
]
