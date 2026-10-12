"""Regression for shutdown generations spanning manager startup."""

import asyncio

import pytest

from app.channels.service import ChannelService


@pytest.mark.asyncio
async def test_late_manager_start_cannot_resurrect_stopped_service(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ChannelService(channels_config={})
    start_entered = asyncio.Event()
    release_start = asyncio.Event()
    manager_running = False
    stop_calls = 0

    async def delayed_manager_start() -> None:
        nonlocal manager_running
        start_entered.set()
        await release_start.wait()
        manager_running = True

    async def manager_stop() -> None:
        nonlocal manager_running, stop_calls
        stop_calls += 1
        manager_running = False

    monkeypatch.setattr(service.manager, "start", delayed_manager_start)
    monkeypatch.setattr(service.manager, "stop", manager_stop)

    starting = asyncio.create_task(service.start())
    await asyncio.wait_for(start_entered.wait(), timeout=1)
    await service.stop()
    assert not service._running
    assert not service._stopping
    release_start.set()
    await asyncio.wait_for(starting, timeout=1)

    assert not service._running
    assert not manager_running
    assert stop_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("start_after_shutdown", [False, True], ids=["queued-before-shutdown", "restart-after-shutdown"])
async def test_late_start_cleanup_preserves_newer_start(
    monkeypatch: pytest.MonkeyPatch,
    start_after_shutdown: bool,
) -> None:
    service = ChannelService(channels_config={})
    first_start_entered = asyncio.Event()
    release_first_start = asyncio.Event()
    newer_start_attempted = asyncio.Event()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    manager_running = False
    start_calls = 0
    stop_calls = 0

    async def manager_start() -> None:
        nonlocal manager_running, start_calls
        start_calls += 1
        if start_calls == 1:
            first_start_entered.set()
            await release_first_start.wait()
        manager_running = True

    async def manager_stop() -> None:
        nonlocal manager_running, stop_calls
        stop_calls += 1
        if stop_calls == 2:
            cleanup_entered.set()
            await release_cleanup.wait()
        manager_running = False

    async def start_again() -> None:
        newer_start_attempted.set()
        await service.start()

    monkeypatch.setattr(service.manager, "start", manager_start)
    monkeypatch.setattr(service.manager, "stop", manager_stop)
    starting = asyncio.create_task(service.start())
    newer_start = None
    try:
        await asyncio.wait_for(first_start_entered.wait(), timeout=1)
        if start_after_shutdown:
            await service.stop()
        newer_start = asyncio.create_task(start_again())
        await asyncio.wait_for(newer_start_attempted.wait(), timeout=1)
        if not start_after_shutdown:
            await service.stop()
    finally:
        release_first_start.set()
        try:
            await asyncio.wait_for(cleanup_entered.wait(), timeout=1)
            assert newer_start is not None and not newer_start.done()
        finally:
            release_cleanup.set()
            tasks = [starting] if newer_start is None else [starting, newer_start]
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)

    # A post-shutdown restart must survive stale cleanup. A start admitted
    # before shutdown must stay invalidated even if it waited for that cleanup.
    assert service._running is start_after_shutdown
    assert manager_running is start_after_shutdown
    assert start_calls == (2 if start_after_shutdown else 1)


@pytest.mark.asyncio
async def test_manager_start_finishing_during_channel_drain_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ChannelService(channels_config={})
    start_entered = asyncio.Event()
    release_start = asyncio.Event()
    channel_stop_entered = asyncio.Event()
    release_channel_stop = asyncio.Event()
    manager_running = False
    stop_calls = 0

    async def delayed_manager_start() -> None:
        nonlocal manager_running
        start_entered.set()
        await release_start.wait()
        manager_running = True

    async def manager_stop() -> None:
        nonlocal manager_running, stop_calls
        stop_calls += 1
        manager_running = False

    class BlockingChannel:
        async def stop(self) -> None:
            channel_stop_entered.set()
            await release_channel_stop.wait()

    monkeypatch.setattr(service.manager, "start", delayed_manager_start)
    monkeypatch.setattr(service.manager, "stop", manager_stop)
    service._channels["blocking"] = BlockingChannel()

    starting = asyncio.create_task(service.start())
    await asyncio.wait_for(start_entered.wait(), timeout=1)
    stopping = asyncio.create_task(service.stop())
    await asyncio.wait_for(channel_stop_entered.wait(), timeout=1)
    assert service._stopping and stop_calls == 1

    release_start.set()
    await asyncio.wait_for(starting, timeout=1)
    assert not manager_running
    assert stop_calls == 2

    release_channel_stop.set()
    await asyncio.wait_for(stopping, timeout=1)
    assert not service._running
    assert not service._stopping
