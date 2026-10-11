from __future__ import annotations

import asyncio

import pytest

from app.scheduler import notification_delivery
from app.scheduler.notification_delivery import NotificationDeliveryWorker


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellations", [1, 3])
async def test_stop_owns_poller_cleanup_through_cancellation(cancellations):
    worker = NotificationDeliveryWorker(delivery_repo=object(), resolve_channel=lambda _: None, stop_timeout_seconds=60)
    poll_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()
    restarted = asyncio.Event()
    generation = 0

    async def poll():
        nonlocal generation
        generation += 1
        if generation > 1:
            restarted.set()
            await worker._stop.wait()
            return
        poll_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await allow_cleanup.wait()
            cleanup_finished.set()

    worker._run_loop = poll
    await worker.start()
    await poll_started.wait()
    first = worker._task
    stop = asyncio.create_task(worker.stop())
    await worker._stop.wait()
    restart = None
    try:
        stop.cancel("first cancellation")
        await asyncio.wait_for(cleanup_started.wait(), timeout=2)
        restart = asyncio.create_task(worker.start())
        for _ in range(cancellations - 1):
            stop.cancel("repeated cancellation")
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not stop.done(), "stop abandoned the poller's admitted cleanup"
        assert worker._task is first
        assert not restart.done(), "restart crossed the old cleanup generation"
        allow_cleanup.set()
        with pytest.raises(asyncio.CancelledError, match="first cancellation"):
            await stop
        assert cleanup_finished.is_set()
        await restart
        await restarted.wait()
    finally:
        allow_cleanup.set()
        await asyncio.gather(stop, return_exceptions=True)
        if restart is not None:
            await restart
        await worker.stop()


@pytest.mark.asyncio
async def test_stop_preserves_poller_cleanup_error_after_caller_cancel():
    worker = NotificationDeliveryWorker(delivery_repo=object(), resolve_channel=lambda _: None, stop_timeout_seconds=60)
    started = asyncio.Event()
    cleanup_started = asyncio.Event()
    allow_failure = asyncio.Event()

    async def poll():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await allow_failure.wait()
            raise RuntimeError("poller cleanup failed")

    worker._run_loop = poll
    await worker.start()
    await started.wait()
    stop = asyncio.create_task(worker.stop())
    await worker._stop.wait()
    stop.cancel("shutdown cancelled")
    await cleanup_started.wait()
    allow_failure.set()
    with pytest.raises(asyncio.CancelledError, match="shutdown cancelled") as caught:
        await stop
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "poller cleanup failed"


@pytest.mark.asyncio
async def test_caller_cancel_does_not_interrupt_timeout_cleanup():
    worker = NotificationDeliveryWorker(delivery_repo=object(), resolve_channel=lambda _: None, stop_timeout_seconds=0.001)
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def poll():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            finished.set()

    worker._run_loop = poll
    await worker.start()
    await started.wait()
    stop = asyncio.create_task(worker.stop())
    try:
        await asyncio.wait_for(cleaning.wait(), timeout=2)
        for message in ("first cancellation", "repeated cancellation"):
            stop.cancel(message)
            await asyncio.sleep(0)
        assert not stop.done()
        release.set()
        with pytest.raises(asyncio.CancelledError, match="first cancellation"):
            await stop
        assert finished.is_set()
        assert worker._task is None
    finally:
        release.set()
        await asyncio.gather(stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_uncancelled_stop_propagates_poller_failure_and_clears_generation():
    worker = NotificationDeliveryWorker(delivery_repo=object(), resolve_channel=lambda _: None)
    started = asyncio.Event()

    async def poll():
        started.set()
        await worker._stop.wait()
        raise RuntimeError("poller failed")

    worker._run_loop = poll
    await worker.start()
    await started.wait()
    with pytest.raises(RuntimeError, match="poller failed"):
        await worker.stop()
    assert worker._task is None


@pytest.mark.asyncio
async def test_repeated_shutdown_cancel_drains_real_repository_call():
    entered = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    class Repository:
        async def reset_stale_sending_rows(self, **kwargs):
            return 0

        async def claim_due_deliveries(self, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                finished.set()

    worker = NotificationDeliveryWorker(delivery_repo=Repository(), resolve_channel=lambda _: None, stop_timeout_seconds=60)
    await worker.start()
    await entered.wait()
    stop = asyncio.create_task(worker.stop())
    await worker._stop.wait()
    try:
        stop.cancel("shutdown cancelled")
        await asyncio.wait_for(cleaning.wait(), timeout=2)
        stop.cancel("shutdown cancelled again")
        await asyncio.sleep(0)
        assert not stop.done()
        release.set()
        with pytest.raises(asyncio.CancelledError, match="^shutdown cancelled$"):
            await stop
        assert finished.is_set()
        assert worker._task is None
    finally:
        release.set()
        await asyncio.gather(stop, return_exceptions=True)


@pytest.mark.asyncio
async def test_grace_deadline_does_not_cancel_caller_started_cleanup_again(monkeypatch):
    entered = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    deadline_observed = asyncio.Event()

    class Repository:
        async def reset_stale_sending_rows(self, **kwargs):
            return 0

        async def claim_due_deliveries(self, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                finished.set()

    worker = NotificationDeliveryWorker(delivery_repo=Repository(), resolve_channel=lambda _: None, stop_timeout_seconds=0.01)
    original_warning = notification_delivery.logger.warning

    def observe_deadline(*args, **kwargs):
        original_warning(*args, **kwargs)
        deadline_observed.set()

    monkeypatch.setattr(notification_delivery.logger, "warning", observe_deadline)
    await worker.start()
    await entered.wait()
    stop = asyncio.create_task(worker.stop())
    await worker._stop.wait()
    try:
        stop.cancel("caller cancelled first")
        await asyncio.wait_for(deadline_observed.wait(), timeout=2)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not stop.done()
        assert worker._task.cancelling() == 1
        release.set()
        with pytest.raises(asyncio.CancelledError, match="caller cancelled first"):
            await stop
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(stop, return_exceptions=True)
