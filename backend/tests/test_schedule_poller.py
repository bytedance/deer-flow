"""Tests for the scheduler poller.

The poller owns everything about *when* the service is asked to work, and
nothing about what the work means. Two behaviours here are load-bearing and
were carried over deliberately from `app/scheduler/service.py`:

  - a failing poll must not kill the loop for the rest of the process life
    (a transient "database is locked" would otherwise silently stop every
    scheduled task until the next restart), and
  - startup reconciliation must not block startup.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.scheduler.poller import SchedulePoller


class _SpyService:
    """Stands in for `ScheduleService`, recording how the poller drove it."""

    def __init__(self, *, run_once_error: Exception | None = None, reconcile_error: Exception | None = None) -> None:
        self.run_once_error = run_once_error
        self.reconcile_error = reconcile_error
        self.run_once_calls: list[datetime] = []
        self.reconcile_calls: list[str] = []
        self.polled = asyncio.Event()

    async def run_once(self, *, now: datetime) -> list:
        self.run_once_calls.append(now)
        self.polled.set()
        if self.run_once_error is not None:
            raise self.run_once_error
        return []

    async def reconcile_on_startup(self, *, error: str) -> tuple[int, int]:
        self.reconcile_calls.append(error)
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return 2, 1


async def _drain(poller: SchedulePoller, service: _SpyService, *, polls: int = 1) -> None:
    """Start the poller, wait for it to poll, then stop it."""
    await poller.start()
    try:
        for _ in range(polls):
            service.polled.clear()
            await asyncio.wait_for(service.polled.wait(), timeout=2)
    finally:
        await poller.stop()


class TestStartupReconciliation:
    @pytest.mark.asyncio
    async def test_start_reconciles_before_polling(self):
        service = _SpyService()
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await _drain(poller, service)
        assert len(service.reconcile_calls) == 1
        assert "restart" in service.reconcile_calls[0]

    @pytest.mark.asyncio
    async def test_a_failed_reconcile_does_not_block_the_loop(self):
        """Whether a partial reconcile blocks startup is the caller's policy,
        and this caller's policy is: log it and keep scheduling. A gateway that
        refuses to start because of leftover rows is worse than one that runs
        with them."""
        service = _SpyService(reconcile_error=RuntimeError("db down"))
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await _drain(poller, service)
        assert service.run_once_calls


class TestPolling:
    @pytest.mark.asyncio
    async def test_polls_repeatedly(self):
        service = _SpyService()
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await _drain(poller, service, polls=3)
        assert len(service.run_once_calls) >= 3

    @pytest.mark.asyncio
    async def test_each_poll_passes_a_tz_aware_now(self):
        service = _SpyService()
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await _drain(poller, service)
        assert all(now.tzinfo is not None for now in service.run_once_calls)

    @pytest.mark.asyncio
    async def test_a_failing_poll_does_not_kill_the_loop(self):
        """The regression this guards: one transient DB error used to end
        scheduling for the rest of the process life."""
        service = _SpyService(run_once_error=RuntimeError("database is locked"))
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await _drain(poller, service, polls=3)
        assert len(service.run_once_calls) >= 3


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_stop_is_awaited_to_completion(self):
        service = _SpyService()
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await poller.start()
        await asyncio.wait_for(service.polled.wait(), timeout=2)
        await poller.stop()
        before = len(service.run_once_calls)
        await asyncio.sleep(0.05)
        assert len(service.run_once_calls) == before

    @pytest.mark.asyncio
    async def test_stop_does_not_wait_out_the_poll_interval(self):
        """The loop waits on a stop event rather than sleeping, so shutdown is
        prompt even with a production-sized interval."""
        service = _SpyService()
        poller = SchedulePoller(service, poll_interval_seconds=300)
        await poller.start()
        await asyncio.wait_for(service.polled.wait(), timeout=2)
        await asyncio.wait_for(poller.stop(), timeout=2)

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        service = _SpyService()
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await poller.start()
        await poller.start()
        try:
            await asyncio.wait_for(service.polled.wait(), timeout=2)
        finally:
            await poller.stop()
        assert len(service.reconcile_calls) == 1

    @pytest.mark.asyncio
    async def test_stop_without_start_is_a_no_op(self):
        poller = SchedulePoller(_SpyService(), poll_interval_seconds=0.01)
        await poller.stop()

    @pytest.mark.asyncio
    async def test_it_can_be_restarted(self):
        service = _SpyService()
        poller = SchedulePoller(service, poll_interval_seconds=0.01)
        await _drain(poller, service)
        await _drain(poller, service)
        assert len(service.reconcile_calls) == 2
