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
