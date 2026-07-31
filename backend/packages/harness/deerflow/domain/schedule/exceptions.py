"""The known errors of the schedule context.

One family under one base class, so the primary adapter can map the whole
family onto protocol codes in a single table. Class names keep the PEP 8
``Error`` suffix; the module is named ``exceptions`` after the AWS
hexagonal guidance's domain folder of the same name.
"""

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


class CorruptStoredScheduleError(ScheduleError):
    """A stored task row can no longer be rebuilt into a valid aggregate.

    Raised by the persistence adapter, never by the aggregate: it means the
    *storage* is damaged, not that a client submitted something invalid --
    which is why it is deliberately absent from the router's status table and
    falls through to the unclassified-500 branch instead of riding
    ``InvalidScheduleError``'s 422.
    """


class ConcurrentUpdateError(ScheduleError):
    """The aggregate changed between this caller's read and its write.

    Raised by the task repository's `save` when the stored version no longer
    matches the aggregate's -- a dispatch or completion committed in between.
    The service retries the read-modify-write a bounded number of times and
    then lets this surface; the router maps it to a retryable conflict.
    """


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
    """The launch definitely did not start a run.

    The adapter may raise this only when it is CERTAIN no run exists -- the
    service releases the task's active slot on this path, so raising it after
    the launch side effect may have happened reopens the #4452 duplicate
    execution. When in doubt, raise LaunchIndeterminateError instead.
    """


class LaunchIndeterminateError(ScheduleError):
    """The launch side effect may have happened, but its identity is unknown.

    Raised by the RunLauncher adapter when the launch call did not fail
    cleanly -- the response could not be decoded, the connection dropped after
    the request was sent, and so on. The service treats this as launched with
    an unknown run id: the execution record stays active so the task's single
    active slot remains held (#4452 / #4504), and reconciliation later settles
    what actually happened.
    """
