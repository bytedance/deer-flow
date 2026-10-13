from __future__ import annotations

import asyncio

import pytest

from app.scheduler.notification_delivery import NotificationDeliveryWorker


@pytest.mark.asyncio
async def test_restart_waits_for_in_progress_stop_to_release_poller_ownership() -> None:
    worker = NotificationDeliveryWorker(
        delivery_repo=object(),
        resolve_channel=lambda _provider: None,
        poll_interval_seconds=60,
        stop_timeout_seconds=5,
    )
    first_started = asyncio.Event()
    allow_first_exit = asyncio.Event()
    second_started = asyncio.Event()
    generation = 0

    async def controlled_loop() -> None:
        nonlocal generation
        generation += 1
        if generation == 1:
            first_started.set()
            await allow_first_exit.wait()
            return
        second_started.set()
        await worker._stop.wait()

    worker._run_loop = controlled_loop

    await worker.start()
    await first_started.wait()
    first_poller = worker._task
    assert first_poller is not None

    stop_task = asyncio.create_task(worker.stop())
    await asyncio.wait_for(worker._stop.wait(), timeout=5)

    assert worker._task is first_poller

    restart_task = asyncio.create_task(worker.start())
    await asyncio.sleep(0)
    assert not restart_task.done()
    assert worker._task is first_poller

    allow_first_exit.set()
    await stop_task
    await restart_task
    await second_started.wait()

    assert worker._task is not first_poller
    await worker.stop()
