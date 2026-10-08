from __future__ import annotations

import asyncio

import pytest

from app.channels import service as channel_service
from app.channels.service import ChannelService
from deerflow import reflection


class _FakeChannel:
    def __init__(self, *, bus: object, config: dict[str, object]) -> None:
        self.is_running = False

    async def start(self) -> None:
        self.is_running = True

    async def stop(self) -> None:
        self.is_running = False


@pytest.mark.asyncio
async def test_restart_is_fenced_while_service_shutdown_is_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ChannelService(channels_config={"fake": {"enabled": True}})
    service._running = True
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()

    # Give stop() a real, already-owned transport to await. It snapshots
    # _channels before awaiting this stop; a late restart must not publish a
    # second transport that is absent from the snapshot.
    existing = _FakeChannel(bus=service.bus, config={})
    existing.is_running = True

    async def blocking_channel_stop() -> None:
        stop_entered.set()
        await release_stop.wait()
        existing.is_running = False

    async def manager_stop() -> None:
        pass

    monkeypatch.setattr(existing, "stop", blocking_channel_stop)
    monkeypatch.setattr(service.manager, "stop", manager_stop)
    monkeypatch.setitem(channel_service._CHANNEL_REGISTRY, "fake", "tests.fake:FakeChannel")
    monkeypatch.setattr(reflection, "resolve_class", lambda *_args, **_kwargs: _FakeChannel)
    service._channels["existing"] = existing

    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(stop_entered.wait(), timeout=1)

    try:
        restarted = await service.restart_channel("fake", reload_config=False)
    finally:
        release_stop.set()
        await asyncio.wait_for(stop_task, timeout=1)

    assert restarted is False
    assert service._channels == {}
    assert service._running is False
    assert service._stopping is False


@pytest.mark.asyncio
async def test_channel_cannot_publish_after_stop_finishes_during_prestart_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ChannelService(channels_config={"buzz": {"enabled": True}})
    service._running = True
    entered_io = asyncio.Event()
    resume_io = asyncio.Event()

    async def held_to_thread(_function: object) -> str:
        entered_io.set()
        await resume_io.wait()
        return "/tmp/buzz_seen_events.json"

    async def manager_stop() -> None:
        pass

    monkeypatch.setattr(channel_service.asyncio, "to_thread", held_to_thread)
    monkeypatch.setattr(service.manager, "stop", manager_stop)
    monkeypatch.setitem(channel_service._CHANNEL_REGISTRY, "buzz", "tests.fake:FakeChannel")
    monkeypatch.setattr(reflection, "resolve_class", lambda *_args, **_kwargs: _FakeChannel)

    start_task = asyncio.create_task(service._start_channel("buzz", {"enabled": True}))
    await asyncio.wait_for(entered_io.wait(), timeout=1)
    await service.stop()
    assert service._stopping is False
    assert service._running is False

    resume_io.set()
    assert await asyncio.wait_for(start_task, timeout=1) is False
    assert service._channels == {}
