"""Scheduled jobs persistence layer.

Two tables back the user-owned scheduled job feature:

- ``scheduled_jobs``: the job definition (trigger, payload, scheduling state)
- ``scheduled_job_runs``: per-execution history rows

All repository methods accept a ``user_id`` keyword argument that defaults
to ``AUTO`` — resolved from the request-scoped ContextVar via
``deerflow.runtime.user_context``. Pass an explicit ``str`` to override
(tests, admin tools), or ``None`` to opt out of the WHERE clause
(migrations only).
"""

from deerflow.persistence.scheduled_jobs.model import ScheduledJobRow
from deerflow.persistence.scheduled_jobs.repository import ScheduledJobRepository

__all__ = ["ScheduledJobRepository", "ScheduledJobRow"]
