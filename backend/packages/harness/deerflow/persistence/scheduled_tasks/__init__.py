"""ORM row of the scheduled_tasks table.

The table definition lives here with the shared engine/alembic
infrastructure; its only reader and writer is the schedule context's
secondary adapter (``app/adapters/schedule/scheduled_task_repository.py``).
"""

from .model import ScheduledTaskRow

__all__ = ["ScheduledTaskRow"]
