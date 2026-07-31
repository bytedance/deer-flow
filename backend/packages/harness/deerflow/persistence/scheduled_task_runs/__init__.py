"""ORM row of the scheduled_task_runs table.

The table definition -- including the partial unique index
``uq_scheduled_task_run_active`` that arbitrates the single active slot --
lives here with the shared engine/alembic infrastructure; its only reader and
writer is the schedule context's secondary adapter
(``app/adapters/schedule/scheduled_run_repository.py``).
"""

from .model import ScheduledTaskRunRow

__all__ = ["ScheduledTaskRunRow"]
