"""Lightweight, zero-dependency scheduler for scheduled jobs.

This package implements the scheduling primitives shared by the
``scheduled_jobs`` feature:

- ``cron_parser``: parses and evaluates 5-field cron expressions without
  pulling in ``croniter`` or ``croniter``-like deps.
- ``time_parser``: parses user-facing time strings (ISO 8601, relative
  like ``"20m"``, epoch milliseconds).
- ``triggers``: AtTrigger / EveryTrigger / CronTrigger implementations
  of the ``Trigger`` protocol.
- ``stagger``: deterministic per-job top-of-hour jitter.
- ``retry``: exponential backoff schedule for consecutive errors.
- ``core``: the asyncio scheduler loop that owns the in-memory job table
  and dispatches due jobs.

Design constraint: this package MUST NOT import from ``app.*`` — it
lives in the harness layer and stays reusable. Application concerns
(Gateway lifespan wiring, IM delivery) live in ``app.scheduled_jobs``.
"""

from deerflow.scheduler.core import Scheduler
from deerflow.scheduler.triggers import (
    AtTrigger,
    CronTrigger,
    EveryTrigger,
    Trigger,
    parse_user_when,
)

__all__ = [
    "AtTrigger",
    "CronTrigger",
    "EveryTrigger",
    "Scheduler",
    "Trigger",
    "parse_user_when",
]
