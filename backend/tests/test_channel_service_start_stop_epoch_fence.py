"""Regression for shutdown completing while ChannelManager.start() is suspended."""

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
