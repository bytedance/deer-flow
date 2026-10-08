from __future__ import annotations

import asyncio

import pytest

from app.channels.service import ChannelService


@pytest.mark.asyncio
async def test_restart_is_fenced_while_service_shutdown_is_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ChannelService(channels_config={"fake": {"enabled": True}})
    service._running = True
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()

    async def blocking_manager_stop() -> None:
        stop_entered.set()
        await release_stop.wait()

    monkeypatch.setattr(service.manager, "stop", blocking_manager_stop)

    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(stop_entered.wait(), timeout=1)

    assert service._stopping is True
    assert await service.restart_channel("fake", reload_config=False) is False
    assert service._channels == {}

    release_stop.set()
    await stop_task

    assert service._running is False
    assert service._stopping is False
