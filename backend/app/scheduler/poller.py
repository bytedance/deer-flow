"""Driving adapter -- the clock that asks the schedule service to work.

This is the only part of the scheduler that knows about time passing. It owns
*when* `ScheduleService.run_once` is called and what happens when a poll fails;
it owns nothing about what a poll means. Everything the old
`app/scheduler/service.py` mixed into its loop -- overlap policy, lease
semantics, budget accounting -- now lives in the domain and reaches this file
only as one awaited call.

Two behaviours here are load-bearing:

  - **A failing poll must not end the loop.** A transient error (SQLite's
    "database is locked" is the realistic one) would otherwise stop every
    scheduled task for the rest of the process life, silently.
  - **Startup reconciliation must not block startup.** The service lets
    reconcile failures propagate on purpose -- whether they are fatal is the
    caller's policy -- and this caller's policy is to log and keep scheduling.
    A gateway refusing to start over leftover rows is worse than one running
    with them.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.domain.schedule.service import ScheduleService

logger = logging.getLogger(__name__)

RESTART_ERROR = "interrupted: gateway restarted before the run reached a terminal state"


class SchedulePoller:
    """Runs `ScheduleService.run_once` on an interval until stopped."""

    def __init__(self, service: ScheduleService, *, poll_interval_seconds: float) -> None:
        self._service = service
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        """Reconcile what a crash left behind, then begin polling.

        Idempotent: a second call while running is a no-op, so a caller cannot
        end up with two loops claiming the same tasks.
        """
        if self._task is not None:
            return
        try:
            stale_runs, stuck_tasks = await self._service.reconcile_on_startup(error=RESTART_ERROR)
            if stale_runs:
                logger.warning("Marked %d stale scheduled task run(s) as interrupted after restart", stale_runs)
            if stuck_tasks:
                logger.warning("Cancelled %d stuck once task(s) after restart", stuck_tasks)
        except Exception:
            logger.exception("Failed to reconcile scheduled tasks at startup; scheduling anyway")
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Signal the loop and wait for the in-flight poll to finish."""
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._service.run_once(now=datetime.now(UTC))
            except Exception:
                logger.exception("Scheduled task poll failed; retrying next interval")
            try:
                # Waiting on the stop event rather than sleeping keeps shutdown
                # prompt at a production-sized interval.
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue
