from __future__ import annotations


class ScheduleError(Exception):
    """Base error for the schedule domain."""


class InvalidScheduleError(ScheduleError):
    """Timezone, cron expression, or run_at is not usable."""


class InvalidContextModeError(ScheduleError):
    """context_mode is unknown, or reuse_thread is missing its thread_id."""


class TaskNotFoundError(ScheduleError):
    """The task does not exist or does not belong to the user."""


class TaskNotMutableError(ScheduleError):
    """The task is currently running and cannot be edited."""


class ThreadNotFoundError(ScheduleError):
    """reuse_thread points at a thread the user cannot access."""


class ActiveRunConflictError(ScheduleError):
    """The task already holds its single active run slot.

    Raised by the run repository when the partial unique index
    ``uq_scheduled_task_run_active`` rejects a second active row. Moved here
    from ``persistence/scheduled_task_runs/sql.py`` (was
    ``ActiveScheduledRunConflict``) so the domain owns its own vocabulary.
    """


class ThreadBusyError(ScheduleError):
    """The execution thread already has an in-flight run.

    Translated by the RunLauncher adapter from ConflictError / HTTP 409.
    This is what removes `from fastapi import HTTPException` from the
    orchestration layer.
    """


class LaunchFailedError(ScheduleError):
    """The run could not be launched for any non-conflict reason."""
